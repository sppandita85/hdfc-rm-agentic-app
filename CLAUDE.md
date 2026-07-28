# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

The venv is `.venv` (Python 3.12). Either activate it or call `.venv/bin/python` directly.

```bash
# Start the required containers (they are NOT part of this repo — the compose file
# lives at ~/docker/postgres-pgadmin/docker-compose.yml, compose project "local-containers")
docker compose -f ~/docker/postgres-pgadmin/docker-compose.yml up -d postgres ollama
docker exec ollama ollama list          # llama3.1 must be present

python -m db.seed                       # DROPS and recreates the hdfc_rm database
python -m scripts.smoke_test            # the test suite — RESEEDS first
streamlit run ui/app.py                 # dashboard on :8501
```

**There is no pytest and no linter.** `scripts/smoke_test.py` is a plain script: numbered
test functions that append to a module-level `FAILURES` list, with `main()` reseeding and
calling them in order. To run one test:

```bash
.venv/bin/python -c "
from scripts import smoke_test as st
st.test_type_2_serviceable_path()
print('FAILURES:', st.FAILURES)"
```

A single test does **not** reseed. Re-running one against an already-processed email hits
the existing checkpoint, and because `agent_path` uses an append reducer the path comes
back doubled. Reseed (or use a fresh `thread_id`) when that matters.

## Architecture

Inbound email → LangGraph pipeline → RM-reviewed draft. Postgres holds both the synthetic
bank data and the LangGraph checkpoints; Ollama runs the local model.

```
START → intent_classifier
          ├─(type_1)→ product_info_agent ──────────────┐
          └─(type_2)→ auth_agent                       │
                        ├─(can_serve)→ data_retrieval ─┤
                        └─(!can_serve)────────────────→┤
                                       response_drafter → END
```

Source of truth: [`graph/state.py`](graph/state.py) (state schema),
[`graph/builder.py`](graph/builder.py) (wiring). Two conditional edges — `route_by_intent`
lives in `intent_classifier.py`, `route_by_auth` in `auth_agent.py`, each next to the node
whose output it branches on.

### The graph ends at the drafter — by design

There is **no `interrupt()` and no human-in-the-loop node.** The graph terminates at
`response_drafter`; the RM's accept/reject/edit decision is handled entirely by the
Streamlit layer and written to `rm_responses`. The Postgres checkpointer is used purely as
a **cache** so re-opening a processed email is instant instead of re-running the LLM. Don't
mistake it for resumable HITL state.

### Provider switching (`INTENT_PROVIDER`)

**Only `intent_classifier` has a choice of provider** — `ollama` (default) or `anthropic`.
Entity extraction, product matching and drafting always run on local Ollama, so no account
or transaction data reaches an external API. The two paths differ in output contract:
Claude uses structured outputs (`messages.parse()` with a Pydantic schema; `intent_type` is
a `Literal` so it compiles to a JSON-schema enum and cannot return a third value), while
Ollama is asked for JSON in the prompt and parsed by `llm/json_parsing.py`, which tolerates
prose and markdown fences.

`classify_method` in state stores the **provider name** (`anthropic` / `ollama` /
`keyword_fallback`); `ui/components/agent_panel.py` maps it to a display label.

### Everything degrades, nothing raises

Each LLM step has a deterministic fallback, so an unreachable model produces a worse answer
rather than a failed run:

| Step | Fallback |
|---|---|
| Intent classification | keyword heuristic (`classify_by_keywords`) |
| Entity extraction | regex pre-pass alone (`entity_prompts.extract_by_regex`) |
| Draft composition | fixed templates (`draft_prompts.template_*`) |

Regex beats the LLM on reference/account identifiers and **wins on those fields** in
`merge_entities()` — small models transpose digits in long alphanumeric IDs.

### The `can_serve` rule is enforced in two places — keep them in sync

`auth_agent` will not serve a request identified only by transaction *type*. A vague email
("I sent some money") is enough for the model to infer `txn_type="transfer"`, and matching
on customer + type alone would report on an arbitrary recent transaction the customer never
asked about. Serving requires a **reference number, or type AND amount together**
(`_has_narrowing_pair`). `data_retrieval_agent`'s fallback branch repeats the same
condition. Change one without the other and retrieval silently widens.

`auth_agent` performs **no real authentication** — it is a pass-through stub by explicit
spec, with a `TODO(real-auth)` marker. Its state interface (`can_serve`, `auth_reason`,
`customer_record`, `extracted_entities`) is deliberately stable so real verification can
drop in without reshaping the graph.

### Two gotchas that have already caused bugs

**Module-level settings binding.** Every module does `from config.settings import settings`,
binding the object at import time. Rebinding `config.settings.settings` does **not** reach
them — patch the binding inside the specific module (`llm.ollama_client.settings`,
`graph.nodes.intent_classifier.settings`). The degraded-mode smoke test does exactly this;
getting it wrong made the test silently pass while still hitting the live service.

**Settings are read once at import**, so Streamlit must be restarted after editing `.env`.

### Streamlit's rerun model

Streamlit re-executes the whole script on every click, so `ui/graph_runner.py` checks
`graph.get_state()` **before** ever calling `invoke()`. "Regenerate draft" works by bumping
a per-email run counter in `st.session_state`, which suffixes the `thread_id` — a genuinely
fresh run rather than a served checkpoint.

### Data layer invariants

- `db/seed_data.py` is pure literals with FKs as **1-based indices**; `db/seed.py` remaps
  them to real serial IDs via `resolve_fk` after insert.
- `seed_data.validate()` runs before anything is written and fails the seed if an email
  quotes a reference number absent from `TRANSACTIONS`. Without it the pipeline runs fine
  and silently retrieves nothing — a broken-looking demo with no code defect. Intentionally
  unresolvable references are whitelisted in `INTENTIONALLY_UNRESOLVABLE_REFS`.
- `emails.intent_type` is **not** seeded — it starts NULL and is written at runtime by the
  classifier. The Type 1/Type 2 split in the source file is ground truth for the smoke
  test, never read by the app.
- `rm_responses` is upserted per email (current decision); `rm_audit_log` is append-only
  (full history). A reject later regenerated and accepted must leave both correct — the
  smoke test asserts this.

## Non-goals

No real authentication, no SMTP (accepting a draft just writes to `rm_responses`), no live
core-banking or SWIFT integration, and no vector search — product matching is scored SQL
`ILIKE` over a 15-row catalogue, which is more accurate and more explainable at that size.
