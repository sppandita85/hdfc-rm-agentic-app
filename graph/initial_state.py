"""Shared helper for building the initial graph state from an `emails` row.
Used by both the Streamlit UI and the smoke test so the two never drift apart."""
from __future__ import annotations


def thread_id_for(email_id: int) -> str:
    return f"email-{email_id}"


def build_initial_state(row: dict) -> dict:
    return {
        "email_id": row["email_id"],
        "customer_email": row["customer_email"],
        "subject": row["subject"],
        "body": row["body"],
        "received_at": str(row["received_at"]),
        "thread_id": thread_id_for(row["email_id"]),
        "agent_path": [],
    }
