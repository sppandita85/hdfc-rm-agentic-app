"""HDFC RM Assist — Streamlit dashboard.

Run with:  streamlit run ui/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allows `streamlit run ui/app.py` from the project root without setting PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from config.settings import settings  # noqa: E402
from db import queries  # noqa: E402
from db.connection import DatabaseUnavailable  # noqa: E402
from llm.anthropic_client import anthropic_available  # noqa: E402
from llm.ollama_client import ollama_available  # noqa: E402
from ui import graph_runner, styles  # noqa: E402
from ui.components import agent_panel, audit_log, email_detail, inbox_list, rm_actions  # noqa: E402

st.set_page_config(page_title="HDFC RM Assist", page_icon="🏦", layout="wide")
styles.inject()

st.markdown(
    f"""
    <div class="hdfc-header">
      <h1>🏦 HDFC RM Assist</h1>
      <p>Multi-agent inbox triage for {settings.rm_name}, {settings.rm_title} —
         every reply is drafted by AI and approved by you before it goes anywhere.</p>
    </div>
    """,
    unsafe_allow_html=True,
)


def _classifier_label() -> str:
    """Names the model the classifier will actually use, so progress text can't claim a
    provider that isn't configured. Derived from settings, never hardcoded."""
    if settings.intent_provider == "anthropic":
        return settings.anthropic_model if settings.anthropic_configured() else "keyword fallback"
    if settings.intent_provider == "ollama":
        return f"{settings.ollama_model} (local)"
    return "keyword fallback"


def _service_banners() -> None:
    """Graceful fallback: name the unreachable service and the fix, rather than crashing."""
    if settings.intent_provider == "anthropic":
        configured, reason = anthropic_available()
        if not configured:
            st.warning(
                f"**Intent classification is set to Claude, but {reason}.** "
                "Classification will fall back to keyword matching (flagged per email in "
                "the Agent trace). Add `ANTHROPIC_API_KEY=...` to your `.env` and restart, "
                "or set `INTENT_PROVIDER=ollama` to classify locally.",
                icon="🔑",
            )
    elif settings.intent_provider != "ollama":
        st.warning(
            f"**Unknown `INTENT_PROVIDER={settings.intent_provider}`.** Expected "
            "`anthropic` or `ollama`; every email will use the keyword fallback.",
            icon="⚠️",
        )

    reachable, error = ollama_available()
    if not reachable:
        # Ollama always does entity extraction and drafting; it only does classification
        # when INTENT_PROVIDER=ollama — so don't claim classification is degraded when
        # Claude is handling it.
        also_classification = (
            " Classification also falls back to keyword matching."
            if settings.intent_provider == "ollama"
            else ""
        )
        st.warning(
            f"**Ollama is unreachable** at `{settings.ollama_host}` ({error}). "
            f"Processing still works, but entity extraction is regex-only and drafts come "
            f"from fixed templates.{also_classification} Start it with "
            "`docker compose -f ~/docker/postgres-pgadmin/docker-compose.yml up -d ollama`.",
            icon="⚠️",
        )


def _load_inbox() -> list[dict] | None:
    try:
        return queries.list_emails()
    except DatabaseUnavailable as exc:
        st.error(f"**Postgres is unreachable.** {exc}", icon="🚫")
        st.stop()
    except Exception as exc:  # noqa: BLE001
        st.error(
            f"**Could not load the inbox.** {exc}\n\n"
            "If the tables are missing, run `python -m db.seed`.",
            icon="🚫",
        )
        st.stop()
    return None


def _run_counter(email_id: int) -> int:
    """How many times 'Regenerate' has been pressed for this email. Bumping it changes the
    checkpointer thread id, which is what forces a genuinely fresh run."""
    return st.session_state.get(f"run_{email_id}", 0)


def render_detail(row: dict) -> None:
    email_id = row["email_id"]
    run = _run_counter(email_id)
    enriched = {**graph_runner.enrich(row, email_id, run), "_run": run}

    email_detail.render(enriched)
    st.divider()

    if not enriched["processed"]:
        st.markdown("#### Agent pipeline")
        st.caption(
            "Not processed yet. Running the pipeline classifies the email, routes it through "
            f"the right agents and drafts a reply. Intent is classified by "
            f"**{_classifier_label()}**; retrieval and drafting run on the local model, so "
            "expect 15–40 seconds overall."
        )
        if st.button("▶︎ Process this email", type="primary", key=f"process_{email_id}"):
            with st.status("Running the agent pipeline…", expanded=True) as status:
                st.write(f"Classifying intent ({_classifier_label()})…")
                result = graph_runner.process_email(row, run)
                for node in result.get("agent_path") or []:
                    st.write(f"✓ {node}")
                status.update(label="Pipeline complete", state="complete", expanded=False)
            queries.record_audit(email_id, "processed", f"path: {' -> '.join(result.get('agent_path') or [])}")
            st.rerun()
        return

    agent_panel.render(enriched)
    st.divider()

    def regenerate() -> None:
        st.session_state[f"run_{email_id}"] = run + 1
        queries.reset_email_status(email_id)
        queries.record_audit(email_id, "regenerated", "RM requested a fresh draft")
        st.rerun()

    rm_actions.render(enriched, regenerate)


# ---------------------------------------------------------------------------
_service_banners()
rows = _load_inbox()

counts = {"new": 0, "processing": 0, "answered": 0}
for row in rows:
    counts[row["status"]] = counts.get(row["status"], 0) + 1

m1, m2, m3, m4 = st.columns(4)
m1.metric("Inbox", len(rows))
m2.metric("New", counts["new"])
m3.metric("In progress", counts["processing"])
m4.metric("Answered", counts["answered"])

inbox_tab, audit_tab = st.tabs(["📥 Inbox", "📋 Audit log"])

with inbox_tab:
    left, right = st.columns([1, 2], gap="medium")

    with left:
        st.markdown("#### Inbox")
        filtered = inbox_list.apply_filters(rows)
        if clicked := inbox_list.render(filtered, st.session_state.get("selected_email_id")):
            st.session_state["selected_email_id"] = clicked
            st.rerun()

    with right:
        selected_id = st.session_state.get("selected_email_id")
        selected = next((r for r in rows if r["email_id"] == selected_id), None)
        if selected is None:
            st.info("Select an email from the inbox to view it and run the agent pipeline.", icon="👈")
        else:
            render_detail(selected)

with audit_tab:
    audit_log.render()
