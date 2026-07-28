# HDFC RM Assist — Build Plan

## Context

`hdfc-rm-agentic-app/` is currently an **empty directory**. We're building, from scratch, a
multi-agent assistant that helps a bank Relationship Manager triage inbound customer emails:
classify each email, route it through the right agents, draft a reply, and let the RM
accept / reject / edit before "sending". This is training material for the eclerx Agentic AI
course, so the code needs to be readable and the agent boundaries obvious.

**Everything runs locally** — Llama 3.1 via the existing Ollama container, Postgres via the
existing `postgres` container. No external API calls, no real SMTP, no real core banking.

### What already exists and is being reused

Two things materially shape this plan:

1. **The Docker stack is already defined** at `~/docker/postgres-pgadmin/docker-compose.yml`
   (compose project `local-containers`): `postgres` (postgres:16, `5432`,
   postgres/postgres/postgres), `ollama` (`11434`), `pgadmin` (`5050`), `phoenix` (`6006`).
   All four containers exist but are **currently stopped**.
2. **A near-identical sibling project exists** at
   `~/Desktop/trainings/hydrofit/demos/multi-agents-heavy-equipment-app/` — same stack
   (LangGraph + Ollama + Postgres + Streamlit), same shape (inbox → agents → draft → human
   review). We mirror its layout and copy its proven helpers rather than reinventing them.

### Deliberate deviations from the sibling project

- **No Phoenix tracing** (user's call) — skip `tracing/`, and drop the `arize-phoenix-otel` /
  `openinference-*` / `opentelemetry-*` dependencies.
- **No `interrupt()` review node** (user's call). The graph is exactly the 5 agents from the
  spec and ends at the Response Drafter. Streamlit owns the RM decision and writes to
  `rm_responses`. The Postgres checkpointer is still used, purely so re-opening an already
  processed email is instant instead of re-running the LLM.

---

## Target layout

```
hdfc-rm-agentic-app/
├── .venv/                     # python3.12 -m venv .venv  (gitignored)
├── .env.example / .env
├── .gitignore
├── requirements.txt
├── README.md
├── config/settings.py         # frozen dataclass loaded from .env
├── db/
│   ├── connection.py          # get_conn() contextmanager, dict_row
│   ├── schema.sql             # 6 tables
│   ├── seed_data.py           # pure data literals
│   ├── seed.py                # drop/create db, apply schema, load data, checkpointer setup
│   └── queries.py             # read helpers + RM-action writes
├── llm/
│   ├── ollama_client.py       # cached ChatOllama w/ hard timeout
│   ├── json_parsing.py        # extract_json() — fence/brace-tolerant
│   ├── intent_prompts.py      # Type 1 / Type 2 classification + keyword fallback
│   ├── entity_prompts.py      # entity extraction for Type 2
│   └── draft_prompts.py       # product-reply / data-reply / cannot-serve prompts
├── graph/
│   ├── state.py               # RMState TypedDict
│   ├── builder.py             # StateGraph wiring
│   ├── checkpointer.py        # long-lived PostgresSaver
│   ├── initial_state.py       # build_initial_state(email_row)
│   └── nodes/
│       ├── intent_classifier.py
│       ├── product_info_agent.py
│       ├── auth_agent.py
│       ├── data_retrieval_agent.py
│       └── response_drafter.py
├── scripts/smoke_test.py      # the project's test suite
└── ui/
    ├── app.py
    └── components/{inbox_list,email_detail,agent_panel,rm_actions,audit_log}.py
```

Files to copy near-verbatim from the sibling (adjusting names/imports only) — these are
already proven against this exact Ollama/Postgres setup:

| New file | Source |
|---|---|
| `llm/json_parsing.py` | `llm/json_parsing.py` (verbatim) |
| `llm/ollama_client.py` | `llm/ollama_client.py` |
| `db/connection.py` | `db/connection.py` |
| `graph/checkpointer.py` | `graph/checkpointer.py` (the long-lived-connection trick and its docstring matter — `from_conn_string()` closes the conn on block exit) |
| `db/seed.py` skeleton | `db/seed.py` (`recreate_database` / `insert_rows` / `resolve_fk` / `print_row_counts`) |
| `config/settings.py` | `config/settings.py`, minus the Phoenix fields |

---

## 1. Data layer

`db/schema.sql` — 6 tables (5 from spec + audit log):

```sql
products       product_id PK, name, category, description, key_features TEXT[],
               eligibility, interest_rate NUMERIC(5,2), fees
customers      customer_id PK, name, email UNIQUE, account_number UNIQUE, phone, kyc_status
emails         email_id PK, customer_email, subject, body, received_at TIMESTAMPTZ,
               status TEXT CHECK (new|processing|answered) DEFAULT 'new',
               intent_type TEXT NULL CHECK (type_1|type_2)
transactions   txn_id PK, customer_id FK, type CHECK (transfer|swift|neft|rtgs),
               amount NUMERIC(14,2), currency, status CHECK (pending|completed|failed|in_transit),
               reference_no UNIQUE, swift_ref, initiated_at, updated_at
rm_responses   response_id PK, email_id FK UNIQUE, draft_text, final_text,
               rm_action CHECK (accepted|rejected|edited), edited_at TIMESTAMPTZ
rm_audit_log   audit_id PK, email_id FK, action, detail, actor, occurred_at DEFAULT now()
```

`rm_responses` is upserted per email (`ON CONFLICT (email_id) DO UPDATE`) so it holds the
current decision; `rm_audit_log` is append-only and is what the "Audit log" UI panel reads —
this is why the extra table exists rather than overloading `rm_responses`.

`db/seed_data.py` — synthetic HDFC-flavoured data:
- **~15 products**: savings, salary account, current account, 3 FD variants, RD, home loan,
  personal loan, car loan, education loan, 2 credit cards, demat, NRE/NRO.
- **~20 customers**: Indian names, `@example.com` emails, 14-digit account numbers, mixed
  `kyc_status` (verified / pending / expired) so the auth node has variety.
- **~60 transactions** spread across the 20 customers, all 4 types, all 4 statuses, with
  realistic `reference_no` (`NEFT2026...`, `RTGS...`) and `swift_ref` (`HDFCINBBXXX...`)
  only on `swift` rows.
- **~40 emails**, roughly half Type 1 / half Type 2. **Critical constraint:** every Type 2
  email must quote a `reference_no`, `swift_ref`, or account number that actually exists in
  `transactions`/`customers`, so `data_retrieval_agent` returns real rows. Include a
  deliberate minority of unserviceable Type 2 emails (vague "where's my money?", unknown
  sender email, non-existent reference) to exercise the `can_serve = false` path.

`db/seed.py` drops and recreates the `hdfc_rm` database, applies the schema, loads data, runs
`PostgresSaver.setup()`, prints row counts. Safe to rerun for a clean demo.

## 2. LangGraph pipeline

`graph/state.py` — `RMState(TypedDict, total=False)`:

```
input:       email_id, customer_email, subject, body, received_at, thread_id
classifier:  intent_type ("type_1"|"type_2"), confidence, reasoning, classify_method
auth:        extracted_entities: dict, can_serve: bool, auth_reason, customer_record
retrieval:   retrieved_data: list|dict|None, data_found: bool, data_source
drafter:     draft_text
bookkeeping: agent_path: list[str]        # appended by every node → transparency panel
```

`graph/builder.py`:

```
START → intent_classifier
          ├─(type_1)→ product_info_agent ──────────────┐
          └─(type_2)→ auth_agent                       │
                        ├─(can_serve)→ data_retrieval ─┤
                        └─(!can_serve)────────────────→┤
                                       response_drafter → END
```

Two conditional edges: `route_by_intent` after the classifier, `route_by_auth` after the auth
agent. `product_info_agent` and `data_retrieval_agent` both fall through to
`response_drafter`.

**Node behaviours**

1. **`intent_classifier`** — Llama 3.1 returns
   `{intent_type, confidence, reasoning}`. Parsed with `extract_json`. On any Ollama failure
   or unparseable output, falls back to a keyword heuristic (`classify_by_keywords` in
   `llm/intent_prompts.py`: account/txn nouns → `type_2`, rate/feature nouns → `type_1`) and
   sets `classify_method="keyword_fallback"`. Writes `intent_type` back to `emails` and flips
   `status` to `processing`. `reasoning` is surfaced in the UI for RM trust.

2. **`product_info_agent`** (Type 1) — SQL keyword/category match against `products` (plain
   `ILIKE` + category scoring, no pgvector), returns top matches into `retrieved_data`.

3. **`auth_agent`** (Type 2) — LLM entity extraction (account_number, reference_no, swift_ref,
   txn_type, amount, currency, date) plus a regex pre-pass for reference formats, since regex
   is more reliable than a small model on alphanumeric IDs. Resolves sender against
   `customers`. Sets `can_serve = (some usable entity present) AND (a matching record
   exists)`, with `auth_reason` explaining the decision.
   **Stub, per spec — no real authentication.** A prominent module docstring + inline
   `# TODO(real-auth):` marker states that a production build would do OTP/KBA/session-token
   verification here, and that the `can_serve` / `auth_reason` interface is intentionally
   stable so that logic can drop in without reshaping the graph.

4. **`data_retrieval_agent`** (Type 2, `can_serve=true` only) — looks up `transactions` by
   `reference_no` → `swift_ref` → (`customer_id` + type/amount) in priority order; returns
   status + full details into `retrieved_data`, sets `data_source` for the transparency panel.

5. **`response_drafter`** — Llama 3.1 composes a plain-text RM-ready draft **strictly grounded
   in `retrieved_data`**, with three prompt variants selected by state: product reply,
   transaction-status reply, and the polite "need more info / cannot verify" reply when
   `can_serve=false` or `data_found=false`. On Ollama failure, emits a deterministic
   template-based draft so the pipeline never dead-ends. Sign-off persona comes from
   `RM_NAME`/`RM_TITLE`/`RM_BANK` in `.env`.

## 3. Streamlit UI — "HDFC RM Assist"

`ui/app.py` — two-pane layout (inbox left, detail right), plus an Audit Log tab.

- **Inbox**: sender, subject, received time, status badge (new/processing/answered), intent
  tag (Type 1 / Type 2). **Filters** by status + intent type, and a free-text search over
  subject/body/sender.
- **Email detail**: full body plus a customer-context card (name, masked account number,
  KYC status) resolved from `customers` by sender email.
- **Process button**: calls `ui/graph_runner.py::process_email()` inside a
  `st.status()` block that lists agent progress as the path resolves. `graph_runner` mirrors
  the sibling's `get_state`-first discipline — Streamlit reruns the whole script on every
  click, so it checks the checkpointer before ever calling `invoke()`.
- **Agent response screen / transparency panel**: classification + confidence + the
  classifier's reasoning trace, which path was taken (`agent_path`), extracted entities, the
  `can_serve` decision with its reason, retrieved data (as a table), and `data_source`.
- **RM actions**: `Accept` | `Reject` | `Accept with Edits` (inline `st.text_area`).
  Persists to `rm_responses` + appends to `rm_audit_log`, sets `emails.status='answered'`.
- **Regenerate draft**: clears that thread's checkpoint and re-invokes the graph.
- **Graceful fallback**: `db/connection.py` and `llm/ollama_client.py` failures surface as
  `st.error` banners naming the unreachable service and the fix, never a stack trace. Every
  LLM node already has a non-LLM fallback path (above), so a dead Ollama degrades the app
  rather than breaking it.

## 4. Environment

`.venv` created in the project directory with `python3.12 -m venv .venv` (host Python is
3.12.0; the sibling project uses the same). `requirements.txt` pins the direct deps —
`langgraph`, `langgraph-checkpoint-postgres`, `langchain-core`, `langchain-ollama`,
`psycopg[binary]`, `psycopg-pool`, `streamlit`, `pandas`, `python-dotenv` — at the versions
the sibling's frozen file proves work together (langgraph 1.2.9, langchain-ollama 1.1.0,
psycopg 3.3.4, streamlit 1.60.0).

`.env.example`:
```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hdfc_rm
ADMIN_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.1
OLLAMA_TIMEOUT_S=60
RM_NAME=Priya Nair
RM_TITLE=Relationship Manager
RM_BANK=HDFC Bank
```

## 5. README

Prerequisites, the container-start step, pgAdmin registration (host `postgres`, **not**
`localhost`, from inside the pgadmin container), venv + install, `.env` table, seeding, smoke
test, running the app, an architecture diagram, and a **Stubs & non-goals** section stating
plainly that authentication is a pass-through, there's no SMTP, and the SWIFT/core-banking
tables are synthetic. Carry over the sibling README's port-5432 shadowing troubleshooting
note — a host Homebrew Postgres silently shadowing the container is a real failure mode here.

---

## Build order

1. Start the Docker stack: `docker compose -f ~/docker/postgres-pgadmin/docker-compose.yml up -d`.
2. `docker exec ollama ollama list` → confirm `llama3.1`.
   **If absent, stop and ask before pulling** (~4.9 GB) — per your instruction.
3. Scaffold dirs, `.gitignore`, `.venv`, `requirements.txt`, install.
4. `config/settings.py`, `db/connection.py`, `llm/{ollama_client,json_parsing}.py` (ported).
5. `db/schema.sql` → `db/seed_data.py` → `db/seed.py`; run `python -m db.seed`.
6. `graph/state.py` → the 5 nodes + prompts → `builder.py` → `checkpointer.py`.
7. `scripts/smoke_test.py`; run it.
8. `db/queries.py` → `ui/graph_runner.py` → `ui/` components → `ui/app.py`.
9. `README.md`.

## Verification

End-to-end, in order — each step gates the next:

1. `docker compose ps` — all containers `Up`; `curl -s localhost:11434/api/tags` lists
   `llama3.1`; `psql -h localhost -p 5432 -U postgres -c '\l'` reaches the container.
2. `python -m db.seed` — prints row counts matching the target volumes
   (15 / 20 / 40 / 60 / 0 / 0).
3. **`python -m scripts.smoke_test`** — the real test. Reseeds, then drives representative
   emails through the graph and asserts:
   - a Type 1 email classifies `type_1`, takes the `product_info_agent` path, and its draft
     mentions a product that exists in `products`;
   - a Type 2 email with a valid `reference_no` classifies `type_2`, gets `can_serve=true`,
     retrieves the matching transaction, and its draft contains that transaction's real
     status;
   - a vague Type 2 email gets `can_serve=false`, **skips** `data_retrieval_agent`
     (asserted via `agent_path`), and drafts a "need more info" reply;
   - all three RM actions (accept / edit / reject) write correctly to `rm_responses` and
     append to `rm_audit_log`;
   - **degraded mode**: with `OLLAMA_HOST` pointed at a dead port, a run still completes via
     the keyword fallback + template draft.
   Prints `SMOKE TEST PASSED`, exits 0/1.
4. `streamlit run ui/app.py` — manually walk one Type 1 and one Type 2 email through
   Process → transparency panel → Accept with Edits, then confirm the row landed in
   `rm_responses` and the Audit Log tab shows it. Exercise Regenerate draft and the inbox
   filters/search.
5. Confirm `emails.intent_type` and `emails.status` were actually updated in Postgres
   (via `psql` or pgAdmin at `localhost:5050`).
