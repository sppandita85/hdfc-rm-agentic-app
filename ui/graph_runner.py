"""Bridges the LangGraph run to Streamlit's rerun-per-interaction execution model.

Streamlit re-executes this whole script on every button click, so we never blindly call
graph.invoke(). graph.get_state() is checked first, and an email that already has a
checkpointed run is served from it — that is the whole reason the checkpointer exists here,
since the graph itself has no interrupt to resume from.
"""
from __future__ import annotations

import streamlit as st

from graph.builder import build_graph
from graph.checkpointer import build_checkpointer
from graph.initial_state import build_initial_state, thread_id_for

# Fields lifted out of graph state into the row dict the UI components render.
_STATE_FIELDS = (
    "intent_type", "confidence", "reasoning", "classify_method",
    "extracted_entities", "can_serve", "auth_reason", "customer_record",
    "retrieved_data", "data_found", "data_source",
    "draft_text", "draft_method", "agent_path",
)


@st.cache_resource
def get_graph():
    """One graph and one checkpointer connection for the life of the Streamlit process."""
    return build_graph(build_checkpointer())


def _config(email_id: int, run: int = 0) -> dict:
    # `run` bumps the thread id so "Regenerate draft" gets a genuinely fresh run instead of
    # being served the existing checkpoint.
    suffix = f"-r{run}" if run else ""
    return {"configurable": {"thread_id": thread_id_for(email_id) + suffix}}


def get_run_state(email_id: int, run: int = 0):
    return get_graph().get_state(_config(email_id, run))


def is_processed(email_id: int, run: int = 0) -> bool:
    return bool(get_run_state(email_id, run).values)


def enrich(row: dict, email_id: int | None = None, run: int = 0) -> dict:
    """Merges whatever checkpointed graph state exists onto an `emails` row. Cheap — a local
    DB read only, no LLM call — so it is safe to call for every row when rendering the inbox."""
    values = get_run_state(email_id or row["email_id"], run).values or {}
    return {**row, **{field: values.get(field) for field in _STATE_FIELDS},
            "processed": bool(values)}


def process_email(row: dict, run: int = 0) -> dict:
    """Runs the pipeline for one email if it has not been run yet, and returns the enriched
    row. A no-op (just a cheap get_state) when a checkpoint already exists."""
    email_id = row["email_id"]
    if not is_processed(email_id, run):
        get_graph().invoke(build_initial_state(row), config=_config(email_id, run))
    return enrich(row, email_id, run)
