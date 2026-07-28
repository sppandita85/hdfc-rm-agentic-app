"""Defensive JSON extraction for small local models that often wrap JSON in prose or fences."""
from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_BRACES_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(raw: str) -> dict | None:
    """Best-effort parse of a dict out of an LLM response. Returns None if nothing parses."""
    if not raw:
        return None

    candidates = [raw.strip()]

    fence_match = _FENCE_RE.search(raw)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    braces_match = _BRACES_RE.search(raw)
    if braces_match:
        candidates.append(braces_match.group(0).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed

    return None
