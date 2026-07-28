"""Left pane: filters, search, and the selectable email list."""
from __future__ import annotations

import streamlit as st

from ui import styles

_STATUS_OPTIONS = ["All", "new", "processing", "answered"]
_INTENT_OPTIONS = ["All", "type_1", "type_2", "Unclassified"]
_INTENT_LABELS = {
    "All": "All", "type_1": "Type 1 · Product", "type_2": "Type 2 · Account",
    "Unclassified": "Unclassified",
}


def apply_filters(rows: list[dict]) -> list[dict]:
    """Renders the filter controls and returns the filtered rows."""
    col_a, col_b = st.columns(2)
    status = col_a.selectbox("Status", _STATUS_OPTIONS, format_func=lambda s: s.title() if s != "All" else "All")
    intent = col_b.selectbox("Intent", _INTENT_OPTIONS, format_func=lambda s: _INTENT_LABELS[s])
    query = st.text_input("Search", placeholder="Sender, subject or body text…", label_visibility="collapsed")

    filtered = rows
    if status != "All":
        filtered = [r for r in filtered if r["status"] == status]
    if intent == "Unclassified":
        filtered = [r for r in filtered if not r["intent_type"]]
    elif intent != "All":
        filtered = [r for r in filtered if r["intent_type"] == intent]
    if query:
        needle = query.lower()
        filtered = [
            r for r in filtered
            if needle in r["subject"].lower()
            or needle in r["body"].lower()
            or needle in r["customer_email"].lower()
            or needle in (r.get("customer_name") or "").lower()
        ]
    return filtered


def render(rows: list[dict], selected_id: int | None) -> int | None:
    """Renders the list. Returns a newly selected email_id, or None if nothing was clicked."""
    st.caption(f"{len(rows)} email(s)")

    if not rows:
        st.info("No emails match these filters.")
        return None

    clicked = None
    for row in rows:
        is_selected = row["email_id"] == selected_id
        with st.container(border=True):
            st.markdown(
                f"{styles.status_badge(row['status'])}{styles.intent_badge(row['intent_type'])}",
                unsafe_allow_html=True,
            )
            st.markdown(f"**{row['subject']}**")
            sender = row.get("customer_name") or row["customer_email"]
            st.caption(f"{sender} · {row['received_at']:%d %b, %H:%M}")
            if st.button(
                "Selected" if is_selected else "Open",
                key=f"open_{row['email_id']}",
                width="stretch",
                type="primary" if is_selected else "secondary",
                disabled=is_selected,
            ):
                clicked = row["email_id"]
    return clicked
