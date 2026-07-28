"""Prompts and the deterministic fallback for Type 1 / Type 2 intent classification.

The taxonomy below is shared by both providers so they can never drift apart. Only the
output contract differs: Claude uses a JSON schema (structured outputs enforce the shape,
so no format instructions are needed), while Llama has to be *asked* for JSON and have it
parsed defensively.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

INTENTS = ("type_1", "type_2")

_TAXONOMY = """You are an intent classifier in a bank's Relationship Manager mailbox.
Classify each inbound customer email into exactly one of two types.

type_1 = GENERAL PRODUCT INFORMATION request. The customer is asking about the bank's
products or policies in general: interest rates, features, eligibility, charges, documents
required, comparisons between products. Answering needs only the public product catalogue.
No access to the customer's own account is required.

type_2 = ACCOUNT OR TRANSACTION SPECIFIC request. The customer is asking about their own
money, their own account, or a specific transaction they made: the status of a transfer,
a payment that has not arrived, a failed or pending remittance, a disputed debit, their own
balance or statement. Answering requires looking up that customer's records in the banking
system.

Decision rule: if answering the email requires reading data belonging to this specific
customer, it is type_2. If a generic brochure would answer it, it is type_1."""

# --- Ollama: must be asked for JSON, then parsed defensively ---
SYSTEM_PROMPT = _TAXONOMY + """

Respond with ONLY a JSON object, no prose and no markdown fences:
{"intent_type": "type_1" or "type_2", "confidence": 0.0 to 1.0, "reasoning": "one short sentence"}"""

# --- Claude: the schema enforces the shape, so no format instructions ---
STRUCTURED_SYSTEM_PROMPT = _TAXONOMY


# Passed to messages.parse() as output_format, which compiles it to a JSON schema the
# response is constrained to — so the shape always validates and there is nothing to parse
# defensively. `intent_type` is a Literal so it compiles to a JSON-schema enum: the API
# cannot return a third value, unlike the Ollama path where that has to be checked.
#
# No class docstring: Pydantic would send it as the schema's `description`, putting
# developer-facing notes into the prompt.
class IntentClassification(BaseModel):
    intent_type: Literal["type_1", "type_2"] = Field(
        description="type_1 for a general product-information request; "
                    "type_2 for an account- or transaction-specific request."
    )
    confidence: float = Field(description="Confidence in the classification, 0.0 to 1.0.")
    reasoning: str = Field(description="One short sentence justifying the classification.")


def build_user_prompt(subject: str, body: str) -> str:
    return f"Subject: {subject}\n\nBody:\n{body}\n\nClassify this email."


# --- Deterministic fallback -------------------------------------------------
# Used when Ollama is unreachable or returns something unparseable. Deliberately simple
# and readable: it only has to be right often enough to keep the app usable while the LLM
# is down, and the UI flags any email classified this way as "keyword fallback".

_TYPE_2_TERMS = (
    "my transfer", "my transaction", "my account", "my payment", "my remittance",
    "status of my", "not received", "not credited", "has not arrived", "still pending",
    "reference number", "reference no", "utr", "swift", "neft", "rtgs", "imps",
    "failed", "reversal", "refund", "debited", "statement", "discrepancy",
    "did not go through", "stuck", "tracking", "beneficiary",
)

_TYPE_1_TERMS = (
    "interest rate", "rate of interest", "eligibility", "eligible", "features",
    "benefits", "charges", "fees", "documents required", "what is the difference",
    "how do i open", "would like to open", "want to open", "tenure", "lock-in",
    "processing fee", "annual fee", "minimum balance", "recommend", "brochure",
)

# Reference-number shapes are the single strongest type_2 signal, so they outweigh
# keyword counts entirely.
_REF_RE = re.compile(r"\b(?:NEFT|RTGS|TRF|SWF|UTR)[A-Z0-9]{6,}\b", re.IGNORECASE)
_ACCOUNT_RE = re.compile(r"\b\d{11,16}\b")


def classify_by_keywords(subject: str, body: str) -> tuple[str, float, str]:
    """Returns (intent_type, confidence, reasoning)."""
    text = f"{subject}\n{body}".lower()

    if _REF_RE.search(text) or _ACCOUNT_RE.search(text):
        return (
            "type_2",
            0.75,
            "Keyword fallback: the email quotes a transaction reference or account number, "
            "which requires a banking-system lookup.",
        )

    type_2_hits = sum(1 for term in _TYPE_2_TERMS if term in text)
    type_1_hits = sum(1 for term in _TYPE_1_TERMS if term in text)

    if type_2_hits > type_1_hits:
        return (
            "type_2",
            min(0.7, 0.45 + 0.05 * type_2_hits),
            f"Keyword fallback: matched {type_2_hits} account/transaction term(s) "
            f"versus {type_1_hits} product term(s).",
        )

    if type_1_hits > 0:
        return (
            "type_1",
            min(0.7, 0.45 + 0.05 * type_1_hits),
            f"Keyword fallback: matched {type_1_hits} product-information term(s) "
            f"versus {type_2_hits} account term(s).",
        )

    # Nothing matched. Default to type_1 — the product path is safe because it never
    # exposes customer data, whereas a wrong type_2 routing would ask an RM to verify
    # a request that was never about an account.
    return (
        "type_1",
        0.35,
        "Keyword fallback: no strong signal either way, defaulted to the product-information "
        "path because it cannot expose customer data.",
    )
