"""Single source of truth for the LangGraph state schema.

A TypedDict (not Pydantic) so state serializes cleanly through the Postgres checkpointer.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict


def _append(left: list[str] | None, right: list[str] | None) -> list[str]:
    """Reducer for agent_path: every node appends its own name rather than overwriting,
    so the finished state carries the exact route the email took through the graph."""
    return (left or []) + (right or [])


class RMState(TypedDict, total=False):
    # --- input (set before the first graph.invoke) ---
    email_id: int
    customer_email: str
    subject: str
    body: str
    received_at: str
    thread_id: str

    # --- intent_classifier output ---
    intent_type: str            # "type_1" (product info) | "type_2" (account specific)
    confidence: float
    reasoning: str              # shown to the RM to justify the routing decision
    classify_method: str        # "llm" | "keyword_fallback"

    # --- authentication_agent output (Type 2 path only) ---
    extracted_entities: dict[str, Any]
    can_serve: bool
    auth_reason: str
    customer_record: dict[str, Any] | None

    # --- product_info_agent / data_retrieval_agent output ---
    retrieved_data: Any         # list[dict] of products, or a single txn dict, or None
    data_found: bool
    data_source: str            # table(s) queried, surfaced in the transparency panel

    # --- response_drafter output ---
    draft_text: str
    draft_method: str           # "llm" | "template_fallback"

    # --- bookkeeping ---
    agent_path: Annotated[list[str], _append]
