# HDFC RM Assist

A local, multi-agent assistant that helps a bank **Relationship Manager (RM)** triage inbound
customer emails and draft replies. Every email is classified, routed through the right agents,
and answered with a grounded draft — but **nothing is ever sent until the RM accepts it**.

**Everything runs locally by default**: Llama 3.1 through Ollama, with Postgres holding
both the synthetic bank data and the LangGraph checkpoints. No external API calls, no key
required. Intent classification can optionally be switched to Claude by setting
`INTENT_PROVIDER=anthropic` — see [Model providers](#model-providers).

---

## Architecture

```
START → intent_classifier
          ├─(type_1)→ product_info_agent ─────────────────┐
          └─(type_2)→ auth_agent                          │
                        ├─(can_serve)→ data_retrieval_agent┤
                        └─(else)──────────────────────────┤
                                          response_drafter ─→ END

                     Streamlit:  [ Accept ] [ Reject ] [ Accept with edits ]
                                          ↓
                              rm_responses + rm_audit_log
```

| Agent | Role |
|---|---|
| **intent_classifier** | Decides **Type 1** (general product info — answerable from the public catalogue, no customer data needed) vs **Type 2** (account/transaction specific — needs a banking-system lookup). Writes `intent_type` back to `emails`. **Model provider is configurable** — see below. Falls back to a keyword heuristic if the provider fails. |
| **product_info_agent** | Type 1 path. Scored SQL keyword/category match against `products`. |
| **auth_agent** | Type 2 path. Extracts entities and decides `can_serve`. **A pass-through stub — no real authentication.** See [Stubs & non-goals](#stubs--non-goals). |
| **data_retrieval_agent** | Type 2 path, only when `can_serve = true`. Resolves a transaction by reference number → SWIFT reference → customer + type + amount. |
| **response_drafter** | Llama 3.1 composes the draft strictly from retrieved data, using one of three prompt variants (product / transaction / cannot-serve). |

The graph **ends** at `response_drafter`. The RM's accept/reject/edit decision is handled by
the Streamlit layer, not by a graph node — there is no `interrupt()`. The Postgres
checkpointer is used purely as a cache, so re-opening an already-processed email is instant
rather than re-running the LLM.

Source of truth: [`graph/state.py`](graph/state.py) for the state schema,
[`graph/builder.py`](graph/builder.py) for the wiring.

### Model providers

The **Intent Classifier is the only agent with a choice of provider**, set by
`INTENT_PROVIDER` in `.env`:

| `INTENT_PROVIDER` | Classifier runs on | Output contract |
|---|---|---|
| `ollama` (default) | Llama 3.1, locally | Asked for JSON in the prompt, then parsed with a fence/brace-tolerant extractor, because small local models routinely wrap JSON in prose. |
| `anthropic` | **Claude** (`claude-opus-5`) via the Anthropic API | **Structured outputs** — a JSON schema the response is constrained to, with `intent_type` as an enum. The shape always validates; there is nothing to parse defensively. |

Everything downstream — entity extraction, product matching, draft composition — **always
runs on the local Ollama model**, regardless of this setting. So on the Type 2 path, no
account or transaction data is sent to the Anthropic API; the classifier only ever sees
the inbound email, which the customer already sent over the public internet.

Whichever provider is selected, a failure (missing key, rate limit, network, or an
unparseable response) degrades to the same deterministic keyword heuristic rather than
failing the run. The Agent trace panel shows which one actually served each
classification — **Claude**, **Llama 3.1**, or **Keyword** — so a silent fallback is
visible rather than mistaken for a working setup.

---

## Prerequisites

- **Docker Desktop**, with the `postgres` (postgres:16) and `ollama` containers published on
  ports `5432` and `11434`. `pgadmin` on `5050` is optional but handy.
- **The `llama3.1` model pulled** into the Ollama container.
- **Python 3.12** on the host.
- **No Anthropic API key needed** — the app runs fully locally out of the box. One is only
  required if you opt into `INTENT_PROVIDER=anthropic`.

---

## 1. Start the containers

```bash
docker compose -f ~/docker/postgres-pgadmin/docker-compose.yml up -d postgres pgadmin ollama
docker compose -f ~/docker/postgres-pgadmin/docker-compose.yml ps
```

Confirm the model is present, and pull it if not (~4.9 GB, one time):

```bash
docker exec ollama ollama list          # should include llama3.1
docker exec ollama ollama pull llama3.1 # only if missing
```

Verify both services answer from the host:

```bash
curl -s http://localhost:11434/api/tags   # lists the installed models
docker exec postgres psql -U postgres -c "SELECT version();"
```

> **Port 5432 already in use?** If you have a native Postgres on the host (e.g. Homebrew) it
> can bind `localhost:5432` ahead of Docker's port proxy and silently shadow the container.
> The symptom is `FATAL: role "postgres" does not exist` while the container is clearly
> running. Check with `lsof -nP -iTCP:5432 -sTCP:LISTEN` — if you see a native `postgres`
> process rather than `com.docker...`, stop it (`brew services stop postgresql@16`) or remap
> the container to another host port.

## 2. Python environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 3. `.env` reference

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/hdfc_rm` | app data + checkpoints |
| `ADMIN_DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/postgres` | used only by the seed script, to create the `hdfc_rm` database |
| `OLLAMA_HOST` | `http://localhost:11434` | |
| `OLLAMA_MODEL` | `llama3.1` | |
| `OLLAMA_TIMEOUT_S` | `60` | hard request timeout, so a wedged model can't hang a run |
| `INTENT_PROVIDER` | `ollama` | `ollama` or `anthropic` — see [Model providers](#model-providers) |
| `ANTHROPIC_API_KEY` | *(empty)* | Only needed if you set `INTENT_PROVIDER=anthropic` |
| `ANTHROPIC_MODEL` | `claude-opus-5` | |
| `ANTHROPIC_EFFORT` | `low` | `low`/`medium`/`high`/`xhigh`/`max` — the cost & latency lever |
| `ANTHROPIC_MAX_TOKENS` | `1024` | ample for a one-label classification response |
| `RM_NAME` / `RM_TITLE` / `RM_BANK` | `Priya Nair` / `Relationship Manager` / `HDFC Bank` | draft sign-off |

`localhost` is correct here because the Python app runs on the **host**, outside Docker.

`.env` is gitignored, so the key stays out of version control. `ANTHROPIC_EFFORT` is set
to `low` because classifying a short email against a two-value taxonomy is not a
reasoning-heavy task — raise it if routing accuracy on your email mix matters more than
latency and cost.

## 4. Seed the database

```bash
python -m db.seed
```

**Drops and recreates** the `hdfc_rm` database, creates the 6 tables, loads the synthetic
dataset, and sets up the LangGraph checkpoint tables. Safe to rerun any time you want a clean
demo — reruns wipe all prior RM decisions and audit history.

Expected output:

```
products         15
customers        20
emails           40
transactions     60
rm_responses      0
rm_audit_log      0
```

Seed data lives in [`db/seed_data.py`](db/seed_data.py) as plain literals. Its `validate()`
function runs before anything is written and fails loudly if an email quotes a reference
number that doesn't exist in `transactions` — the failure mode that otherwise makes the demo
look broken for reasons unrelated to the code.

## 5. Run the test suite

```bash
python -m scripts.smoke_test
```

This is the project's test suite. It reseeds, then drives representative emails through the
graph and asserts:

1. a **Type 1** email routes to `product_info_agent`, skips `auth_agent`, and its draft
   references a product that genuinely exists in the catalogue;
2. a **Type 2** email with a valid reference gets `can_serve = true`, retrieves the matching
   transaction, and its draft quotes that transaction's **real** status and reference;
3. a **vague Type 2** email gets `can_serve = false`, **skips** `data_retrieval_agent`
   (asserted via `agent_path`), and drafts a holding reply that claims no status;
4. **accept / accept-with-edits / reject** all write correctly to `rm_responses`, mark the
   email answered, and append to `rm_audit_log` — including that re-deciding an email upserts
   the response but *appends* a second audit row;
5. **degraded mode**: with `OLLAMA_HOST` pointed at a dead port, the run still completes via
   the keyword classifier, the regex entity extractor and the template drafter.

Prints `SMOKE TEST PASSED` and exits 0 on success; exits 1 with a list of failures otherwise.

## 6. Run the dashboard

```bash
streamlit run ui/app.py
```

Opens at `http://localhost:8501`.

- **Inbox** (left) — sender, subject, time, status badge and intent tag, with **filters** by
  status and intent plus free-text **search** over sender, subject and body.
- **Email detail** (right) — the full body plus a customer-context card (name, masked account
  number, phone, KYC status).
- **Process** — runs the pipeline for that email and shows each agent as it completes. Takes
  roughly 15–40 seconds on a local model. Results are checkpointed, so re-opening is instant.
- **Agent trace** — the transparency panel: classification with confidence and the model's own
  reasoning, the path taken through the graph (skipped nodes struck through), extracted
  entities, the `can_serve` decision and its reason, the retrieved records, and the exact
  lookup used.
- **RM actions** — Accept, Reject (with a reason), Accept with edits (inline editable box), and
  Regenerate draft.
- **Audit log** tab — every RM action with a timestamp, plus the current decision per email.

Emails are processed **on demand**, one at a time, rather than all 40 on first load.

---

## Stubs & non-goals

These are deliberate, per the brief — not oversights.

- **No real authentication.** `auth_agent` does **not** verify that the sender is who they
  claim to be. It answers only the mechanical question *can this request be served* — did the
  email carry a usable identifier, and does a matching record exist — and logs that decision.
  A production build would do OTP / knowledge-based authentication / a signed portal session
  here, and would verify the customer actually owns the referenced transaction. The state
  interface (`can_serve`, `auth_reason`, `customer_record`, `extracted_entities`) is kept
  stable so that logic can drop in without reshaping the graph. See the module docstring and
  the `TODO(real-auth)` marker in [`graph/nodes/auth_agent.py`](graph/nodes/auth_agent.py).
- **No email is ever sent.** There is no SMTP integration. "Accept" writes the final text to
  `rm_responses` and marks the email answered — nothing leaves the machine.
- **No live core banking or SWIFT.** The `transactions` table stands in for both. `swift_ref`
  values are synthetic.
- **No vector search.** Product matching is scored SQL `ILIKE` over a 15-row catalogue, which
  is more accurate *and* more explainable than embeddings at this size — the RM can see the
  match score.

### One design decision worth knowing

`auth_agent` will **not** serve a request identified only by transaction *type*. A vague email
("I sent some money and it hasn't arrived") is enough for the model to infer
`txn_type = "transfer"`, and matching on customer + type alone would then pull that customer's
most recent transfer and confidently report on a transaction they never asked about. Serving
requires either a transaction reference, or a type **and** amount together. This is why some
Type 2 emails in the seed data deliberately land on the "need more info" path.

---

## Troubleshooting

- **`Postgres is unreachable` banner** — the container isn't running, something else holds
  port 5432 (see the note in step 1), or the database hasn't been seeded yet.
- **`Ollama is unreachable` banner** — the app keeps working in degraded mode: classification
  falls back to keyword matching (flagged in the UI) and drafts come from fixed templates.
  Start it with `docker compose … up -d ollama`.
- **Processing is slow** — expected. It's two Llama 3.1 calls per email on local hardware.
  Check `docker exec ollama ollama ps` to see whether the model is loaded or busy, and raise
  `OLLAMA_TIMEOUT_S` if you see timeouts in the logs.
- **`DROP DATABASE … is being accessed by other users`** — a running Streamlit process still
  holds the checkpointer connection. The seed script terminates other backends automatically,
  but stopping the app first is cleaner.
- **Classification looks wrong** — check the **Classified by** metric in the Agent trace
  panel. If it says *Keyword*, the configured provider failed and the deterministic
  fallback was used; routing is best-effort in that mode.
- **Everything says "Keyword" and a 🔑 banner is showing** — `INTENT_PROVIDER=anthropic`
  but `ANTHROPIC_API_KEY` is unset. Add it to `.env` and restart Streamlit (settings are
  read once at import). `python -m scripts.smoke_test` reports this as an explicit SKIP.
- **`AuthenticationError: invalid x-api-key` in the logs** — the key is present but wrong
  or revoked. The run still completes via the keyword fallback.
