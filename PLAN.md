# HDFC RM Assist — Build Plan (as built)

> **Status: delivered and verified.** Every item below is implemented, the smoke test
> passes, and the project is pushed to
> [github.com/sppandita85/hdfc-rm-agentic-app](https://github.com/sppandita85/hdfc-rm-agentic-app).
> This document has been updated from the original pre-build plan to record what was
> actually built — including three things that changed during implementation, in
> [Deviations](#deviations-from-the-original-plan).
>
> For day-to-day work in this repo, read [CLAUDE.md](CLAUDE.md) — it covers the commands
> and the non-obvious architecture. This file is the record of *why* the design is what it
> is.

## Context

Built from scratch in an empty directory: a multi-agent assistant that helps a bank
Relationship Manager triage inbound customer emails — classify each email, route it through
the right agents, draft a reply, and let the RM accept / reject / edit before "sending".
Training material for the eclerx Agentic AI course, so readability and obvious agent
boundaries were priorities over cleverness.

Runs locally by default: Llama 3.1 via Ollama, Postgres for both the synthetic bank data
and the LangGraph checkpoints. No real SMTP, no real core banking. Intent classification
can optionally call Claude — see [Deviations](#deviations-from-the-original-plan).

### What was reused rather than reinvented

1. **The Docker stack already existed** at `~/docker/postgres-pgadmin/docker-compose.yml`
   (compose project `local-containers`): `postgres` (postgres:16, `5432`,
   postgres/postgres/postgres), `ollama` (`11434`), `pgadmin` (`5050`), `phoenix` (`6006`).
   Nothing in this repo defines containers.
2. **A near-identical sibling project** at
   `~/Desktop/trainings/hydrofit/demos/multi-agents-heavy-equipment-app/` — same stack
   (LangGraph + Ollama + Postgres + Streamlit), same shape (inbox → agents → draft → human
   review). Its layout was mirrored and these helpers ported near-verbatim rather than
   rewritten: `llm/json_parsing.py`, `llm/ollama_client.py`, `db/connection.py`,
   `graph/checkpointer.py` (the long-lived-connection trick matters —
   `PostgresSaver.from_conn_string()` closes its connection on block exit), and the
   `db/seed.py` skeleton. Its pinned dependency versions were reused as a known-good set.

### Deliberate design decisions

- **No Phoenix tracing** (user's call) — no `tracing/` package, and the
  `arize-phoenix-otel` / `openinference-*` / `opentelemetry-*` dependencies are absent.
  The `phoenix` container in the compose stack is simply unused.
- **No `interrupt()` review node** (user's call). The graph is exactly the 5 agents from
  the spec and **ends at the Response Drafter**. Streamlit owns the RM decision and writes
  to `rm_responses`. The Postgres checkpointer is still used, purely so re-opening an
  already-processed email is instant instead of re-running the LLM — it is a cache, not
  resumable human-in-the-loop state.

---

## What was built

```
hdfc-rm-agentic-app/
├── .venv/                     # python3.12 -m venv .venv  (gitignored)
├── .env.example / .env        # .env gitignored, incl. every .env.* variant
├── CLAUDE.md                  # guidance for future Claude Code sessions
├── PLAN.md / README.md
├── requirements.txt
├── config/settings.py         # frozen dataclass loaded from .env
├── db/
│   ├── connection.py          # get_conn() ctx manager + DatabaseUnavailable
│   ├── schema.sql             # 6 tables
│   ├── seed_data.py           # pure literals + validate()
│   ├── seed.py                # drop/create db, schema, data, checkpointer setup
│   └── queries.py             # inbox reads + RM-action writes
├── llm/
│   ├── ollama_client.py       # cached ChatOllama w/ hard timeout
│   ├── anthropic_client.py    # Claude classifier (structured outputs)
│   ├── json_parsing.py        # fence/brace-tolerant extract_json()
│   ├── intent_prompts.py      # shared taxonomy + schema + keyword fallback
│   ├── entity_prompts.py      # entity extraction + regex pre-pass
│   └── draft_prompts.py       # 3 prompt variants + 3 template fallbacks
├── graph/
│   ├── state.py               # RMState TypedDict (agent_path uses an append reducer)
│   ├── builder.py             # StateGraph wiring
│   ├── checkpointer.py        # long-lived PostgresSaver
│   ├── initial_state.py
│   └── nodes/                 # the 5 agents
├── scripts/smoke_test.py      # the test suite
└── ui/
    ├── app.py, styles.py, graph_runner.py
    └── components/{inbox_list,email_detail,agent_panel,rm_actions,audit_log}.py
```

### Data layer — 6 tables

The 5 from the spec (`products`, `customers`, `emails`, `transactions`, `rm_responses`)
plus **`rm_audit_log`**. The extra table exists because `rm_responses` is upserted per
email and therefore only ever holds the *latest* decision — it cannot satisfy the "audit
log of every RM action with timestamp" requirement on its own. A reject that is later
regenerated and accepted must leave both a correct current state and a full history; the
smoke test asserts exactly that.

Seed volumes as specified: **15 products / 20 customers / 40 emails / 60 transactions.**

`seed_data.validate()` runs before anything is written and fails the seed if an email
quotes a reference number absent from `TRANSACTIONS`. This guards the expensive-to-debug
failure mode: the pipeline runs fine, retrieval silently finds nothing, and the demo looks
broken for reasons unrelated to the code. Deliberately unresolvable references (for the
`can_serve = false` path) are whitelisted in `INTENTIONALLY_UNRESOLVABLE_REFS`.

`emails.intent_type` is **not** seeded — it starts NULL and is written at runtime by the
classifier, so classification is a genuine test rather than a lookup.

### LangGraph pipeline

```
START → intent_classifier
          ├─(type_1)→ product_info_agent ──────────────┐
          └─(type_2)→ auth_agent                       │
                        ├─(can_serve)→ data_retrieval ─┤
                        └─(!can_serve)────────────────→┤
                                       response_drafter → END
```

Two conditional edges: `route_by_intent` (in `intent_classifier.py`) and `route_by_auth`
(in `auth_agent.py`), each colocated with the node whose output it branches on.

Every LLM step has a deterministic fallback, so an unreachable model degrades the answer
rather than failing the run: classification → keyword heuristic, entity extraction → regex
only, drafting → fixed templates.

`auth_agent` performs **no real authentication** — a pass-through stub per the spec, with a
`TODO(real-auth)` marker and a state interface (`can_serve`, `auth_reason`,
`customer_record`, `extracted_entities`) kept stable so real verification can drop in
without reshaping the graph.

### UI

Two-pane inbox with status/intent filters and free-text search; email detail with a
customer-context card; on-demand **Process** (not eager — 40 emails through a local model
on load would take ~20 minutes); an agent transparency panel showing classification,
confidence, the model's reasoning, the path taken with skipped nodes struck through,
extracted entities, the `can_serve` decision and the retrieved records; RM actions
(Accept / Reject / Accept with edits / Regenerate); and an Audit Log tab.

---

## Deviations from the original plan

Three things changed after the plan was approved. All are in the shipped code.

### 1. `auth_agent` rule tightened — a real defect the smoke test caught

The plan specified `can_serve = (entity present) AND (record exists)`. In practice, for a
vague email ("I sent some money and it hasn't arrived"), the model inferred
`txn_type="transfer"`, and matching on customer + type alone pulled that customer's most
recent transfer and reported on it confidently — **answering about a transaction the
customer never asked about.** That is precisely the wrong-record risk a bank cannot accept.

Serving now requires a **transaction reference, or a type AND amount together**
(`_has_narrowing_pair`). An account number identifies the *customer*, not the
*transaction*, so it resolves who is asking but never suffices on its own. The same
condition is duplicated inline in `data_retrieval_agent`'s fallback branch — **the two must
stay in sync**, or retrieval silently widens.

### 2. Intent classification became provider-switchable

Added after the initial build at the user's request, then defaulted back to local.
`INTENT_PROVIDER` selects `ollama` (default) or `anthropic`:

| Provider | Model | Output contract |
|---|---|---|
| `ollama` (default) | Llama 3.1, local | Asked for JSON in the prompt, parsed defensively by `json_parsing.py` |
| `anthropic` | `claude-opus-5` | Structured outputs — `messages.parse()` with a Pydantic schema; `intent_type` is a `Literal`, so it compiles to a JSON-schema enum and a third value is impossible |

**Only the classifier is switchable.** Entity extraction, product matching and drafting
always run on local Ollama, so no account or transaction data reaches an external API — the
classifier only ever sees the inbound email the customer already sent over the internet.
Effort defaults to `low`: classifying a short email against a two-value taxonomy is not
reasoning-heavy (~3s per call observed).

### 3. `.gitignore` widened to `.env.*`

The original rule matched the exact name `.env` only. That would not have caught a stray
`.env.bak` / `.env.local` / `.env.save` carrying a real key into a public commit — a
near-miss during this build. Now `.env.*` with `!.env.example` negated so the template
still ships.

---

## Verification

All of the following were run against live services, not asserted from reading code.

1. **Services** — containers up; `llama3.1` present in Ollama; Postgres 16.14 reachable
   from the host via Docker's proxy (checked that no native Homebrew Postgres was shadowing
   port 5432, which is a real failure mode here).
2. **`python -m db.seed`** — row counts exactly 15 / 20 / 40 / 60 / 0 / 0.
3. **`python -m scripts.smoke_test`** → **SMOKE TEST PASSED**. Six numbered sections:
   Type 1 routing and product grounding; Type 2 serviceable (correct reference extracted,
   real transaction retrieved, draft quotes the real status); Type 2 unserviceable
   (`can_serve=false`, `data_retrieval_agent` **skipped** — asserted via `agent_path` — and
   the holding draft claims no status); all three RM actions incl. upsert-vs-append
   semantics; the configured intent provider genuinely *served* the classification (not a
   silent fallback); and degraded mode with the local model pointed at a dead port.
4. **UI driven headlessly** via Streamlit's `AppTest` — 23 checks covering render, filters,
   search, the transparency panel, clicking **Process** through the real pipeline, and
   **Accept with edits** persisting to Postgres.
5. **Draft grounding spot-checked** — e.g. a real run quoted reference `RTGS2026070202`
   with status *in transit*, matching the seeded row exactly, with no invented settlement
   date.

### Known gap

The `anthropic` provider path is exercised only when `ANTHROPIC_API_KEY` is set. Smoke test
section [5] reports an explicit **SKIP** rather than passing silently when it isn't — worth
preserving, because the keyword fallback is accurate enough on the seed emails that every
other test still passes with a broken Claude setup.

## Run it

```bash
docker compose -f ~/docker/postgres-pgadmin/docker-compose.yml up -d postgres ollama
python -m db.seed
python -m scripts.smoke_test
streamlit run ui/app.py
```
