"""Entity extraction for the Type 2 path: prompt plus a regex pre-pass.

The regex pre-pass exists because small local models are unreliable at copying long
alphanumeric identifiers verbatim — they transpose and hallucinate digits. Reference
numbers and account numbers have a fixed, cheap-to-match shape, so regex handles those and
the LLM is left to pick up the softer fields (transaction type, amount, currency) where it
is actually better than a pattern.
"""
from __future__ import annotations

import re

SYSTEM_PROMPT = """You extract structured details from a bank customer's email so that a
Relationship Manager can look the request up in the core banking system.

Extract only what is explicitly stated in the email. Never invent or guess a value. If a
field is not present, use null.

Respond with ONLY a JSON object, no prose and no markdown fences:
{
  "account_number": string or null,
  "reference_no": string or null,
  "swift_ref": string or null,
  "txn_type": "transfer" | "swift" | "neft" | "rtgs" | null,
  "amount": number or null,
  "currency": string or null,
  "date_mentioned": string or null
}"""


def build_user_prompt(subject: str, body: str) -> str:
    return f"Subject: {subject}\n\nBody:\n{body}\n\nExtract the details."


_REFERENCE_RE = re.compile(r"\b(?:NEFT|RTGS|TRF)\d{6,}\b", re.IGNORECASE)
_SWIFT_REF_RE = re.compile(r"\b(?:SWF\d{6,}|HDFCINBB[A-Z0-9]{3,})\b", re.IGNORECASE)
_ACCOUNT_RE = re.compile(r"\b\d{14}\b")
_TXN_TYPE_RE = re.compile(r"\b(neft|rtgs|swift|transfer|wire|remittance)\b", re.IGNORECASE)

_TXN_TYPE_MAP = {
    "neft": "neft",
    "rtgs": "rtgs",
    "swift": "swift",
    "wire": "swift",
    "remittance": "swift",
    "transfer": "transfer",
}

VALID_TXN_TYPES = ("transfer", "swift", "neft", "rtgs")


def extract_by_regex(subject: str, body: str) -> dict:
    """Deterministic extraction of the identifier-shaped fields. Always safe to trust over
    the LLM's version of the same field."""
    text = f"{subject}\n{body}"
    entities: dict = {}

    if match := _REFERENCE_RE.search(text):
        entities["reference_no"] = match.group(0).upper()
    if match := _SWIFT_REF_RE.search(text):
        entities["swift_ref"] = match.group(0).upper()
    if match := _ACCOUNT_RE.search(text):
        entities["account_number"] = match.group(0)
    if match := _TXN_TYPE_RE.search(text):
        entities["txn_type"] = _TXN_TYPE_MAP[match.group(0).lower()]

    return entities


def merge_entities(llm_entities: dict | None, regex_entities: dict) -> dict:
    """Regex wins on the identifier fields it covers; the LLM fills in the rest."""
    merged = {
        "account_number": None,
        "reference_no": None,
        "swift_ref": None,
        "txn_type": None,
        "amount": None,
        "currency": None,
        "date_mentioned": None,
    }

    for key, value in (llm_entities or {}).items():
        if key in merged and value not in (None, "", "null"):
            merged[key] = value

    if merged["txn_type"] not in VALID_TXN_TYPES:
        merged["txn_type"] = None

    if merged["amount"] is not None:
        try:
            merged["amount"] = float(str(merged["amount"]).replace(",", ""))
        except (TypeError, ValueError):
            merged["amount"] = None

    # Regex overrides last, so it always wins where it found something.
    merged.update(regex_entities)
    return merged
