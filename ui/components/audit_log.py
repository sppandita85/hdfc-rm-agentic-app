"""Audit Log tab: every RM action, newest first, plus the current decision per email."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from db import queries

_ACTION_LABELS = {
    "accepted": "Accepted",
    "edited": "Accepted with edits",
    "rejected": "Rejected",
    "processed": "Processed by pipeline",
    "regenerated": "Draft regenerated",
}


def render() -> None:
    st.markdown("#### Audit log")
    st.caption(
        "Append-only trail of every RM action. Re-deciding an email adds a new row here "
        "while replacing the current decision in `rm_responses`."
    )

    entries = queries.list_audit_log()
    if not entries:
        st.info("No RM actions recorded yet. Process an email and accept, edit or reject its draft.")
        return

    st.dataframe(
        pd.DataFrame([
            {
                "When": e["occurred_at"].strftime("%d %b %Y, %H:%M:%S"),
                "Action": _ACTION_LABELS.get(e["action"], e["action"]),
                "Email": e["subject"],
                "Customer": e["customer_email"],
                "Detail": e["detail"] or "",
                "Actor": e["actor"],
            }
            for e in entries
        ]),
        hide_index=True,
        width="stretch",
    )

    st.markdown("#### Current decisions")
    responses = queries.list_responses()
    if not responses:
        st.caption("No decisions recorded yet.")
        return

    st.dataframe(
        pd.DataFrame([
            {
                "Email": r["subject"],
                "Customer": r["customer_email"],
                "Intent": r["intent_type"] or "—",
                "Decision": _ACTION_LABELS.get(r["rm_action"], r["rm_action"]),
                "Decided": r["edited_at"].strftime("%d %b %Y, %H:%M"),
                "Final text": (r["final_text"] or "")[:80] + ("…" if (r["final_text"] or "") else ""),
            }
            for r in responses
        ]),
        hide_index=True,
        width="stretch",
    )
