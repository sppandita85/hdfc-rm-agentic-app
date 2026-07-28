"""Right pane, bottom: the generated draft and the RM's Accept / Reject / Edit decision."""
from __future__ import annotations

import streamlit as st

from db import queries


def render(row: dict, on_regenerate) -> None:
    draft = row.get("draft_text") or ""
    email_id = row["email_id"]

    st.markdown("#### Draft reply")

    if row.get("draft_method") == "template_fallback":
        st.warning(
            "This draft came from the deterministic template, not the model — Ollama was "
            "unreachable. It is accurate but blunt; edit before sending.",
            icon="⚠️",
        )

    existing = queries.get_response(email_id)
    if existing:
        label = {"accepted": "Accepted", "edited": "Accepted with edits", "rejected": "Rejected"}
        st.info(
            f"Already actioned: **{label.get(existing['rm_action'], existing['rm_action'])}** "
            f"on {existing['edited_at']:%d %b %Y, %H:%M}. Submitting again will replace that decision.",
            icon="📌",
        )

    edited = st.text_area(
        "Draft (editable — edit here and use *Accept with edits*)",
        value=draft,
        height=340,
        key=f"draft_{email_id}_{row.get('_run', 0)}",
    )

    col1, col2, col3, col4 = st.columns([1, 1.3, 1, 1])

    if col1.button("Accept", key=f"accept_{email_id}", type="primary", width="stretch"):
        queries.record_rm_action(email_id, draft, "accepted", final_text=draft)
        st.success("Accepted and logged. (No email is actually sent — see README.)")
        st.rerun()

    if col2.button("Accept with edits", key=f"edit_{email_id}", width="stretch"):
        if edited.strip() == draft.strip():
            st.warning("The text is unchanged. Use **Accept** instead, or edit the draft first.")
        else:
            queries.record_rm_action(email_id, draft, "edited", final_text=edited)
            st.success("Edited version accepted and logged.")
            st.rerun()

    if col3.button("Reject", key=f"reject_{email_id}", width="stretch"):
        st.session_state[f"rejecting_{email_id}"] = True

    if col4.button("Regenerate", key=f"regen_{email_id}", width="stretch"):
        on_regenerate()

    if st.session_state.get(f"rejecting_{email_id}"):
        with st.form(f"reject_form_{email_id}"):
            reason = st.text_input("Reason for rejection (logged to the audit trail)")
            submitted = st.form_submit_button("Confirm rejection")
            if submitted:
                queries.record_rm_action(email_id, draft, "rejected", detail=reason or None)
                st.session_state[f"rejecting_{email_id}"] = False
                st.rerun()
