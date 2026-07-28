"""End-to-end smoke test — this project's test suite.

Reseeds the database, drives representative emails through the graph, and asserts the
routing, retrieval, grounding and RM-action write paths all behave. Finishes by pointing
OLLAMA_HOST at a dead port to prove the degraded-mode fallbacks keep the pipeline alive.

Usage: python -m scripts.smoke_test
Exits 0 and prints SMOKE TEST PASSED on success; exits 1 with a list of failures otherwise.
"""
from __future__ import annotations

import sys
import time

from config.settings import settings
from db import queries, seed, seed_data
from db.connection import get_conn
from graph.builder import build_graph
from graph.checkpointer import build_checkpointer
from graph.initial_state import build_initial_state, thread_id_for

FAILURES: list[str] = []
_GRAPH = None


def check(condition: bool, label: str, detail: str = "") -> bool:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))
        FAILURES.append(label + (f" :: {detail}" if detail else ""))
    return bool(condition)


def get_graph():
    """One graph, one checkpointer connection, for the whole process."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph(build_checkpointer())
    return _GRAPH


def email_by_subject(subject: str) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM emails WHERE subject = %s", (subject,))
            row = cur.fetchone()
    if row is None:
        raise AssertionError(f"Seed email not found: {subject!r}")
    return dict(row)


def run(row: dict) -> dict:
    config = {"configurable": {"thread_id": thread_id_for(row["email_id"])}}
    started = time.time()
    result = get_graph().invoke(build_initial_state(row), config=config)
    print(f"        (ran in {time.time() - started:.1f}s, path: {' -> '.join(result.get('agent_path', []))})")
    return result


# ---------------------------------------------------------------------------
def test_type_1_product_path() -> None:
    print("\n[1] Type 1 — product information request")
    row = email_by_subject(seed_data.SAMPLE_TYPE_1_SUBJECT)
    state = run(row)

    check(state.get("intent_type") == "type_1",
          "classified as type_1", f"got {state.get('intent_type')!r}: {state.get('reasoning')!r}")
    check("product_info_agent" in state.get("agent_path", []),
          "took the product_info_agent path", str(state.get("agent_path")))
    check("auth_agent" not in state.get("agent_path", []),
          "skipped auth_agent", str(state.get("agent_path")))
    check(bool(state.get("data_found")), "retrieved at least one product")

    # Grounding: the draft must talk about a product that genuinely exists in the catalogue.
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM products")
            names = [r["name"] for r in cur.fetchall()]
    draft = (state.get("draft_text") or "").lower()
    # Match on the distinguishing part of the name, not the shared "HDFC" prefix.
    hit = next((n for n in names if n.replace("HDFC ", "").lower()[:12] in draft), None)
    check(hit is not None, "draft references a real catalogue product", f"draft was: {draft[:220]!r}")

    check(bool(state.get("draft_text")), "produced a draft")
    _assert_intent_persisted(row["email_id"], "type_1")


def test_type_2_serviceable_path() -> None:
    print("\n[2] Type 2 — serviceable, valid reference number")
    row = email_by_subject(seed_data.SAMPLE_TYPE_2_SERVICEABLE_SUBJECT)
    state = run(row)

    check(state.get("intent_type") == "type_2",
          "classified as type_2", f"got {state.get('intent_type')!r}: {state.get('reasoning')!r}")
    check("auth_agent" in state.get("agent_path", []), "took the auth_agent path")
    check(state.get("can_serve") is True, "auth check cleared it", str(state.get("auth_reason")))
    check("data_retrieval_agent" in state.get("agent_path", []), "ran data_retrieval_agent")

    entities = state.get("extracted_entities") or {}
    check(entities.get("reference_no") == seed_data.SAMPLE_TYPE_2_SERVICEABLE_REF,
          "extracted the correct reference number", f"got {entities.get('reference_no')!r}")

    txn = state.get("retrieved_data")
    check(isinstance(txn, dict) and txn.get("reference_no") == seed_data.SAMPLE_TYPE_2_SERVICEABLE_REF,
          "retrieved the matching transaction", str(txn)[:200])

    # Grounding: the real status must appear in the draft, not a hallucinated one.
    if isinstance(txn, dict):
        draft = (state.get("draft_text") or "").lower()
        status = txn["status"]
        wording = {"in_transit": ("transit", "in transit", "not yet"),
                   "completed": ("complete", "success", "credited"),
                   "pending": ("pending", "yet to be processed"),
                   "failed": ("fail", "unsuccessful")}[status]
        check(any(w in draft for w in wording),
              f"draft reflects the real status ({status})", f"draft was: {draft[:220]!r}")
        check(txn["reference_no"].lower() in draft,
              "draft quotes the reference number", f"draft was: {draft[:220]!r}")

    _assert_intent_persisted(row["email_id"], "type_2")


def test_type_2_unserviceable_path() -> None:
    print("\n[3] Type 2 — unserviceable, no usable identifier")
    row = email_by_subject(seed_data.SAMPLE_TYPE_2_UNSERVICEABLE_SUBJECT)
    state = run(row)

    check(state.get("intent_type") == "type_2",
          "classified as type_2", f"got {state.get('intent_type')!r}: {state.get('reasoning')!r}")
    check(state.get("can_serve") is False, "auth check declined it", str(state.get("auth_reason")))
    check("data_retrieval_agent" not in state.get("agent_path", []),
          "SKIPPED data_retrieval_agent", str(state.get("agent_path")))
    check(bool(state.get("auth_reason")), "recorded an auth reason")
    check(bool(state.get("draft_text")), "still produced a holding draft")

    # It must not invent a status it never looked up.
    draft = (state.get("draft_text") or "").lower()
    check(not any(w in draft for w in ("has been completed", "was successful", "has failed")),
          "holding draft does not claim a transaction status", f"draft was: {draft[:220]!r}")


def _assert_intent_persisted(email_id: int, expected: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT intent_type, status FROM emails WHERE email_id = %s", (email_id,))
            row = cur.fetchone()
    check(row["intent_type"] == expected,
          f"intent_type persisted to emails as {expected}", f"got {row['intent_type']!r}")
    check(row["status"] in ("processing", "answered"),
          "email status advanced past 'new'", f"got {row['status']!r}")


def test_rm_actions() -> None:
    print("\n[4] RM actions — accept / edit / reject")
    rows = [
        email_by_subject(seed_data.SAMPLE_TYPE_1_SUBJECT),
        email_by_subject(seed_data.SAMPLE_TYPE_2_SERVICEABLE_SUBJECT),
        email_by_subject(seed_data.SAMPLE_TYPE_2_UNSERVICEABLE_SUBJECT),
    ]

    queries.record_rm_action(rows[0]["email_id"], "DRAFT A", "accepted", final_text="DRAFT A")
    queries.record_rm_action(rows[1]["email_id"], "DRAFT B", "edited", final_text="EDITED BODY")
    queries.record_rm_action(rows[2]["email_id"], "DRAFT C", "rejected", detail="Not accurate enough")

    accepted = queries.get_response(rows[0]["email_id"])
    edited = queries.get_response(rows[1]["email_id"])
    rejected = queries.get_response(rows[2]["email_id"])

    check(accepted["rm_action"] == "accepted" and accepted["final_text"] == "DRAFT A",
          "accept persisted to rm_responses", str(accepted))
    check(edited["rm_action"] == "edited" and edited["final_text"] == "EDITED BODY",
          "accept-with-edits stored the edited text", str(edited))
    check(rejected["rm_action"] == "rejected" and rejected["final_text"] is None,
          "reject stored with no final_text", str(rejected))

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM emails WHERE email_id = ANY(%s)",
                        ([r["email_id"] for r in rows],))
            statuses = {r["status"] for r in cur.fetchall()}
    check(statuses == {"answered"}, "all three emails marked answered", str(statuses))

    audit = queries.list_audit_log()
    logged = {(a["email_id"], a["action"]) for a in audit}
    check((rows[0]["email_id"], "accepted") in logged
          and (rows[1]["email_id"], "edited") in logged
          and (rows[2]["email_id"], "rejected") in logged,
          "all three actions appended to rm_audit_log", str(sorted(logged)))

    # Upsert must replace the decision, not duplicate the row, while the audit log grows.
    before = len(audit)
    queries.record_rm_action(rows[2]["email_id"], "DRAFT C2", "accepted", final_text="DRAFT C2")
    after = queries.get_response(rows[2]["email_id"])
    check(after["rm_action"] == "accepted", "re-deciding an email upserts rm_responses", str(after))
    check(len(queries.list_audit_log()) == before + 1,
          "re-deciding appends a second audit row rather than overwriting")


def test_intent_provider() -> None:
    """Verifies the configured intent provider actually served the classification.

    Without this, a misconfigured Claude setup is invisible: the classifier silently
    drops to the keyword heuristic, which is accurate enough on the seed emails that
    every other test still passes.
    """
    print(f"\n[5] Intent provider — configured as {settings.intent_provider!r}")

    if settings.intent_provider == "anthropic" and not settings.anthropic_configured():
        print("  SKIP  ANTHROPIC_API_KEY is not set — the Claude path was NOT exercised.")
        print("        Add the key to .env and re-run to verify it end to end.")
        print("        (Classification is falling back to keyword matching until then.)")
        return

    row = email_by_subject(seed_data.SAMPLE_TYPE_2_SERVICEABLE_SUBJECT)
    config = {"configurable": {"thread_id": f"provider-{row['email_id']}"}}
    state = get_graph().invoke(build_initial_state(row), config=config)

    check(state.get("classify_method") == settings.intent_provider,
          f"classification served by {settings.intent_provider}",
          f"got {state.get('classify_method')!r} — the provider failed and fell back")
    check(state.get("intent_type") == "type_2",
          "provider classified the email correctly", str(state.get("intent_type")))
    check(bool(state.get("reasoning")), "provider returned a reasoning trace")

    if settings.intent_provider == "anthropic":
        confidence = state.get("confidence")
        check(isinstance(confidence, float) and 0.0 <= confidence <= 1.0,
              "structured output produced a valid confidence", repr(confidence))


def test_degraded_mode() -> None:
    """Ollama unreachable: the run must still complete via the keyword + template fallbacks."""
    print("\n[6] Degraded mode — local model unreachable")
    import graph.nodes.intent_classifier as classifier_module
    import llm.ollama_client as ollama_module

    # Patch the binding inside each module specifically, NOT config.settings.settings.
    # Both do `from config.settings import settings`, so each holds its own reference to
    # the original object — rebinding the config module's attribute would leave them
    # happily using the real values and this test silently vacuous.
    original = ollama_module.settings
    # Port 1 is reserved and never listens, so the client fails fast instead of hanging.
    dead = type(original)(
        **{**original.__dict__, "ollama_host": "http://localhost:1", "ollama_timeout_s": 2.0,
           "intent_provider": "ollama"}
    )
    ollama_module.settings = dead
    # Pin the classifier to Ollama too. Otherwise, with INTENT_PROVIDER=anthropic, the
    # classifier never touches Ollama and "fell back to keywords" would pass for the
    # wrong reason (or not at all) rather than proving the local fallback works.
    classifier_original = classifier_module.settings
    classifier_module.settings = dead
    ollama_module.reset_llm()

    try:
        row = email_by_subject(seed_data.SAMPLE_TYPE_2_SERVICEABLE_SUBJECT)
        # Fresh thread id so the checkpointer can't serve the earlier successful result.
        config = {"configurable": {"thread_id": f"degraded-{row['email_id']}"}}
        state = get_graph().invoke(build_initial_state(row), config=config)

        check(state.get("classify_method") == "keyword_fallback",
              "classifier fell back to keywords", str(state.get("classify_method")))
        check(state.get("intent_type") == "type_2",
              "keyword fallback still routed to type_2", str(state.get("intent_type")))
        check((state.get("extracted_entities") or {}).get("reference_no")
              == seed_data.SAMPLE_TYPE_2_SERVICEABLE_REF,
              "regex still extracted the reference without the LLM")
        check(state.get("data_found") is True, "retrieval still worked (it is pure SQL)")
        check(state.get("draft_method") == "template_fallback",
              "drafter fell back to the template", str(state.get("draft_method")))
        check(bool(state.get("draft_text")), "degraded run still produced a usable draft")
    finally:
        ollama_module.settings = original
        classifier_module.settings = classifier_original
        ollama_module.reset_llm()


def main() -> int:
    print("=" * 72)
    print("HDFC RM Assist — smoke test")
    print("=" * 72)

    print("\n[0] Reseeding the database")
    seed.main()

    test_type_1_product_path()
    test_type_2_serviceable_path()
    test_type_2_unserviceable_path()
    test_rm_actions()
    test_intent_provider()
    test_degraded_mode()

    print("\n" + "=" * 72)
    if FAILURES:
        print(f"SMOKE TEST FAILED — {len(FAILURES)} check(s) failed:")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
