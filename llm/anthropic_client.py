"""Claude client for the intent classifier.

Only the Intent Classifier agent uses this. Entity extraction and draft composition stay
on the local Ollama model, so no customer data leaves the machine on the Type 2 path —
classification only ever sees the inbound email, which the customer already sent over the
public internet.

Intent classification is a single-call task (one email in, one label out), so this uses
`client.messages.parse()` with a Pydantic schema rather than an agent loop or tool use.
"""
from __future__ import annotations

import logging

import anthropic

from config.settings import settings
from llm.intent_prompts import IntentClassification, STRUCTURED_SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    """Process-wide Claude client.

    Constructed with no arguments so the SDK's own credential resolution applies —
    ANTHROPIC_API_KEY (which python-dotenv has already loaded from .env), then any other
    source the SDK supports. Note the constructor does NOT validate the key; an absent or
    wrong key surfaces as an AuthenticationError on the first request, which is why
    settings.anthropic_configured() is checked separately for the UI banner.
    """
    global _client
    if _client is None:
        _client = anthropic.Anthropic(timeout=30.0, max_retries=2)
    return _client


def reset_client() -> None:
    """Drops the cached client. Used by the smoke test when it swaps settings."""
    global _client
    _client = None


def classify_intent(subject: str, body: str) -> dict | None:
    """Returns {intent_type, confidence, reasoning} or None if Claude could not classify.

    None means "fall back" — the caller drops to the keyword heuristic. Never raises.
    """
    if not settings.anthropic_configured():
        logger.warning("ANTHROPIC_API_KEY is not set; skipping the Claude classifier.")
        return None

    try:
        response = get_client().messages.parse(
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            system=STRUCTURED_SYSTEM_PROMPT,
            # Effort is the cost/latency lever. Classifying a short email against a
            # two-value taxonomy is not a reasoning-heavy task, so "low" is the default
            # here — it keeps thinking shallow without disabling it (disabling thinking
            # is capped at "high" effort on Claude Opus 5 anyway, and has its own
            # failure modes). Raise via ANTHROPIC_EFFORT if routing accuracy matters more
            # than latency on your email mix.
            output_config={"effort": settings.anthropic_effort},
            output_format=IntentClassification,
            messages=[{"role": "user", "content": build_user_prompt(subject, body)}],
        )
    except anthropic.AuthenticationError:
        logger.warning("Claude rejected the API key; falling back.", exc_info=True)
        return None
    except anthropic.RateLimitError:
        logger.warning("Claude rate limit hit while classifying; falling back.", exc_info=True)
        return None
    except anthropic.APIStatusError as exc:
        logger.warning("Claude API error %s while classifying; falling back.", exc.status_code, exc_info=True)
        return None
    except anthropic.APIConnectionError:
        logger.warning("Could not reach the Claude API; falling back.", exc_info=True)
        return None

    # Safety classifiers can decline a request: HTTP 200, stop_reason "refusal", and
    # content that is empty or partial. Reading .parsed_output without this check would
    # blow up on the refusal rather than degrading. A bank email should never trip this,
    # but the keyword fallback absorbs it if one ever does.
    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None)
        logger.warning("Claude declined to classify (category=%s); falling back.", category)
        return None

    parsed = response.parsed_output
    if parsed is None:
        logger.warning("Claude returned no parsed output; falling back.")
        return None

    return {
        "intent_type": parsed.intent_type,
        "confidence": parsed.confidence,
        "reasoning": parsed.reasoning,
    }


def anthropic_available() -> tuple[bool, str]:
    """Cheap config check for the UI's status banner. Does not call the API."""
    if not settings.anthropic_configured():
        return False, "ANTHROPIC_API_KEY is not set"
    return True, ""
