"""Right pane, middle: the transparency panel.

Shows the RM exactly what the pipeline concluded and why — classification with the
model's own reasoning, the route taken through the graph, extracted entities, the auth
decision, and the retrieved records. This is what makes the draft trustworthy enough to
send: an RM can see the evidence rather than taking the model's word for it.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import styles

_METHOD_LABELS = {
    "anthropic": "Claude",
    "ollama": "Llama 3.1",
    "keyword_fallback": "Keyword",
}

# Every node, in graph order, so the ones that were skipped can be shown struck through.
_ALL_NODES = [
    "intent_classifier", "product_info_agent", "auth_agent",
    "data_retrieval_agent", "response_drafter",
]


def _path_html(agent_path: list[str] | None) -> str:
    taken = set(agent_path or [])
    parts = []
    for node in _ALL_NODES:
        if node in taken:
            parts.append(f"<b>{node}</b>")
        else:
            parts.append(f'<span class="skipped">{node}</span>')
    return '<div class="agent-path">' + "  →  ".join(parts) + "</div>"


def render(row: dict) -> None:
    st.markdown("#### Agent trace")

    # --- classification ---
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        st.markdown("**Classification**")
        st.markdown(styles.intent_badge(row.get("intent_type")), unsafe_allow_html=True)
    confidence = row.get("confidence")
    c2.metric("Confidence", f"{confidence:.0%}" if isinstance(confidence, (int, float)) else "—")
    method = row.get("classify_method") or "—"
    c3.metric("Classified by", _METHOD_LABELS.get(method, method))

    if method == "keyword_fallback":
        st.warning(
            "Classified by the deterministic keyword fallback because the configured "
            "provider was unreachable, unauthenticated, or returned unusable output. "
            "Double-check this routing.",
            icon="⚠️",
        )

    if reasoning := row.get("reasoning"):
        st.caption(f"**Classifier reasoning:** {reasoning}")

    # --- path ---
    st.markdown("**Path taken**")
    st.markdown(_path_html(row.get("agent_path")), unsafe_allow_html=True)

    # --- Type 2: auth + entities ---
    if row.get("intent_type") == "type_2":
        st.markdown("**Authentication check**")
        can_serve = row.get("can_serve")
        if can_serve:
            st.success(f"can_serve = True — {row.get('auth_reason', '')}", icon="✅")
        else:
            st.error(f"can_serve = False — {row.get('auth_reason', '')}", icon="🚫")
        st.caption(
            "Pass-through stub: this checks only whether the request *can* be served, not "
            "whether the sender is who they claim to be. No real identity verification runs here."
        )

        entities = row.get("extracted_entities") or {}
        present = {k: v for k, v in entities.items() if v not in (None, "", [])}
        st.markdown("**Extracted entities**")
        if present:
            st.dataframe(
                pd.DataFrame([{"Field": k, "Value": str(v)} for k, v in present.items()]),
                hide_index=True, width="stretch",
            )
        else:
            st.caption("No entities could be extracted from this email.")

    # --- retrieved data ---
    st.markdown("**Retrieved data**")
    data = row.get("retrieved_data")
    if not row.get("data_found") or not data:
        st.caption("No records were retrieved for this email.")
    elif isinstance(data, dict):
        st.dataframe(
            pd.DataFrame([{"Field": k, "Value": str(v)} for k, v in data.items()]),
            hide_index=True, width="stretch",
        )
    else:
        st.dataframe(
            pd.DataFrame([
                {
                    "Product": p.get("name"),
                    "Category": p.get("category"),
                    "Rate (%)": p.get("interest_rate"),
                    "Match score": p.get("match_score"),
                }
                for p in data
            ]),
            hide_index=True, width="stretch",
        )

    if source := row.get("data_source"):
        st.caption(f"**Source:** `{source}`")
