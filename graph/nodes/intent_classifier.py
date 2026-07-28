"""Agent 1 - Intent Classifier.

Decides whether an email is a general product-information request (type_1, no customer
data needed) or an account/transaction-specific request (type_2, needs a banking lookup),
then writes that decision back to the `emails` table.

This is the one agent with a choice of model provider, set by INTENT_PROVIDER:

    anthropic -> Claude via the Anthropic API, using structured outputs (a JSON schema
                 the response is constrained to, so the shape always validates)
    ollama    -> Llama 3.1 locally, asked for JSON and parsed defensively

Either way a failure degrades to the same deterministic keyword heuristic, so the
pipeline classifies something no matter which providers are reachable. Everything
downstream — entity extraction, drafting — always runs on the local model.
"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import settings
from db.connection import get_conn
from graph.state import RMState
from llm.intent_prompts import INTENTS, SYSTEM_PROMPT, build_user_prompt, classify_by_keywords
from llm.json_parsing import extract_json
from llm.ollama_client import get_llm

logger = logging.getLogger(__name__)


def _persist(email_id: int, intent_type: str) -> None:
    """Records the classification on the email row. Best-effort: a DB hiccup here must not
    lose the classification the graph already computed and is carrying in state."""
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE emails SET intent_type = %s, "
                "status = CASE WHEN status = 'new' THEN 'processing' ELSE status END "
                "WHERE email_id = %s",
                (intent_type, email_id),
            )
    except Exception:
        logger.warning("Could not persist intent_type for email %s", email_id, exc_info=True)


def _classify_with_ollama(subject: str, body: str) -> dict | None:
    """Llama 3.1 has to be asked for JSON and parsed defensively — small local models
    routinely wrap it in prose or markdown fences. Returns None to trigger the fallback."""
    try:
        response = get_llm().invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=build_user_prompt(subject, body)),
        ])
        return extract_json(response.content)
    except Exception:
        logger.warning("Ollama call failed during intent classification; using keyword fallback.", exc_info=True)
        return None


def intent_classifier(state: RMState) -> dict:
    subject = state.get("subject", "")
    body = state.get("body", "")

    provider = settings.intent_provider
    if provider == "anthropic":
        # Imported lazily so a missing `anthropic` package only breaks the Claude path,
        # not the whole graph.
        from llm.anthropic_client import classify_intent

        parsed = classify_intent(subject, body)
    elif provider == "ollama":
        parsed = _classify_with_ollama(subject, body)
    else:
        logger.warning("Unknown INTENT_PROVIDER %r; using the keyword fallback.", provider)
        parsed = None

    if parsed and parsed.get("intent_type") in INTENTS:
        try:
            confidence = max(0.0, min(1.0, float(parsed.get("confidence"))))
        except (TypeError, ValueError):
            confidence = 0.6
        result = {
            "intent_type": parsed["intent_type"],
            "confidence": confidence,
            "reasoning": str(parsed.get("reasoning") or "No reasoning returned by the model."),
            "classify_method": provider,
        }
    else:
        intent_type, confidence, reasoning = classify_by_keywords(subject, body)
        result = {
            "intent_type": intent_type,
            "confidence": confidence,
            "reasoning": reasoning,
            "classify_method": "keyword_fallback",
        }

    _persist(state["email_id"], result["intent_type"])
    return {**result, "agent_path": ["intent_classifier"]}


def route_by_intent(state: RMState) -> str:
    """Conditional edge: type_1 goes straight to the product catalogue, type_2 must pass
    through the authentication agent first."""
    return "product_info" if state.get("intent_type") == "type_1" else "authentication"
