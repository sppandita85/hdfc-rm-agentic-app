"""Agent 5 - Response Drafter (terminal node).

Composes the RM-ready draft from whatever the upstream agents put in state, using one of
three prompt variants. Every variant has a deterministic template fallback, so an
unreachable Ollama degrades the draft quality rather than failing the run.
"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from graph.state import RMState
from llm import draft_prompts as dp
from llm.ollama_client import get_llm

logger = logging.getLogger(__name__)


def _invoke(system_prompt: str, user_prompt: str) -> str | None:
    try:
        response = get_llm().invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        text = (response.content or "").strip()
        return text or None
    except Exception:
        logger.warning("Ollama call failed while drafting; using the template fallback.", exc_info=True)
        return None


def response_drafter(state: RMState) -> dict:
    subject = state.get("subject", "")
    body = state.get("body", "")
    data = state.get("retrieved_data")
    data_found = bool(state.get("data_found"))

    if state.get("intent_type") == "type_1" and data_found:
        draft = _invoke(dp.PRODUCT_SYSTEM_PROMPT, dp.build_product_prompt(subject, body, data))
        fallback = lambda: dp.template_product_reply(data)  # noqa: E731

    elif state.get("intent_type") == "type_2" and data_found:
        draft = _invoke(
            dp.TRANSACTION_SYSTEM_PROMPT,
            dp.build_transaction_prompt(subject, body, data, state.get("customer_record")),
        )
        fallback = lambda: dp.template_transaction_reply(data)  # noqa: E731

    else:
        # can_serve=False, or a lookup that found nothing (either path). Both mean the same
        # thing to the customer: we cannot answer yet and need more detail.
        reason = state.get("auth_reason") or (
            "No matching information was found for this request in the available records."
        )
        draft = _invoke(dp.CANNOT_SERVE_SYSTEM_PROMPT, dp.build_cannot_serve_prompt(subject, body, reason))
        fallback = dp.template_cannot_serve_reply

    if draft:
        return {"draft_text": draft, "draft_method": "llm", "agent_path": ["response_drafter"]}
    return {"draft_text": fallback(), "draft_method": "template_fallback", "agent_path": ["response_drafter"]}
