"""Prompts and deterministic templates for the response_drafter node.

Three variants, selected by state:
  - PRODUCT      : Type 1, grounded in rows from `products`
  - TRANSACTION  : Type 2 where a matching transaction was found
  - CANNOT_SERVE : Type 2 where authentication or lookup could not be completed

Each has a matching template_*() function used when Ollama is unreachable, so the pipeline
always produces something an RM can work with rather than dead-ending.
"""
from __future__ import annotations

import json
from typing import Any

from config.settings import settings

_SIGNOFF = f"{settings.rm_name}\n{settings.rm_title}\n{settings.rm_bank}"

_BASE_RULES = f"""You are drafting an email reply on behalf of {settings.rm_name},
{settings.rm_title} at {settings.rm_bank}. The draft will be reviewed by a human
Relationship Manager before it is sent.

Rules:
- Use ONLY the facts given below. Never invent rates, dates, amounts, timelines or policies.
- If a detail is not in the given facts, do not mention it at all.
- Write plain text only. No markdown, no bullet characters other than "-", no HTML.
- Be warm, concise and professional. Two to four short paragraphs.
- Open by addressing the customer, and close with exactly this sign-off:

{_SIGNOFF}

Output ONLY the email body text. Do not add a subject line, and do not explain yourself."""

PRODUCT_SYSTEM_PROMPT = _BASE_RULES + """

You are answering a general product-information enquiry. Summarise the relevant product
details that answer the customer's question. If several products were retrieved, briefly
compare them and recommend the one that best fits what the customer asked for."""

TRANSACTION_SYSTEM_PROMPT = _BASE_RULES + """

You are answering an enquiry about a specific transaction. State the transaction's current
status clearly and early. Quote the reference number, amount and currency exactly as given.
Explain what the status means in practical terms for the customer, and what happens next.
Do not promise a settlement date unless one is given in the facts."""

CANNOT_SERVE_SYSTEM_PROMPT = _BASE_RULES + """

You could NOT look up the customer's request, for the reason given below. Write a polite
holding reply that:
- acknowledges their concern and apologises for the inconvenience,
- explains, without technical jargon and without blaming the customer, that you need more
  information to locate the record,
- asks specifically for the missing details (transaction reference number, exact amount,
  date, and the account number involved),
- reassures them that it will be handled as soon as those details arrive.

Never state or imply that the transaction failed, succeeded, or is at any particular stage —
you do not know. Do not ask for passwords, OTPs, card numbers or CVVs."""


def _facts_block(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def build_product_prompt(subject: str, body: str, products: list[dict]) -> str:
    return (
        f"Customer's email:\nSubject: {subject}\n\n{body}\n\n"
        f"Retrieved product facts:\n{_facts_block(products)}\n\n"
        "Draft the reply."
    )


def build_transaction_prompt(subject: str, body: str, txn: dict, customer: dict | None) -> str:
    customer_line = f"\nCustomer on record: {_facts_block(customer)}" if customer else ""
    return (
        f"Customer's email:\nSubject: {subject}\n\n{body}\n"
        f"{customer_line}\n\n"
        f"Transaction found in the banking system:\n{_facts_block(txn)}\n\n"
        "Draft the reply."
    )


def build_cannot_serve_prompt(subject: str, body: str, reason: str) -> str:
    return (
        f"Customer's email:\nSubject: {subject}\n\n{body}\n\n"
        f"Reason the lookup could not be completed (internal, do not quote verbatim):\n{reason}\n\n"
        "Draft the reply."
    )


# ---------------------------------------------------------------------------
# Deterministic fallbacks, used when Ollama is unreachable.
# ---------------------------------------------------------------------------
_STATUS_WORDING = {
    "completed": "has been completed successfully",
    "pending": "is currently pending",
    "in_transit": "is in transit and has not yet been credited to the beneficiary",
    "failed": "was unsuccessful",
}


def template_product_reply(products: list[dict]) -> str:
    if not products:
        return template_cannot_serve_reply()

    lines = ["Dear Customer,", "", "Thank you for writing in. Here are the details you asked for:", ""]
    for product in products[:3]:
        lines.append(f"{product['name']}")
        lines.append(f"  {product['description']}")
        if product.get("interest_rate") is not None:
            lines.append(f"  Indicative rate: {product['interest_rate']} percent per annum")
        lines.append(f"  Eligibility: {product['eligibility']}")
        lines.append(f"  Charges: {product['fees']}")
        lines.append("")
    lines += [
        "Please do let me know if you would like to proceed or need anything clarified.",
        "",
        "Warm regards,",
        _SIGNOFF,
    ]
    return "\n".join(lines)


def template_transaction_reply(txn: dict) -> str:
    wording = _STATUS_WORDING.get(txn["status"], f"is currently marked as {txn['status']}")
    reference = txn.get("swift_ref") or txn["reference_no"]
    return "\n".join([
        "Dear Customer,",
        "",
        f"Thank you for writing in regarding your {txn['type'].upper()} transaction.",
        "",
        f"Your transaction with reference {reference} for {txn['currency']} "
        f"{txn['amount']} {wording}. It was initiated on "
        f"{txn['initiated_at']:%d %B %Y at %H:%M} and last updated on "
        f"{txn['updated_at']:%d %B %Y at %H:%M}.",
        "",
        "Please let me know if you need any further assistance on this.",
        "",
        "Warm regards,",
        _SIGNOFF,
    ])


def template_cannot_serve_reply() -> str:
    return "\n".join([
        "Dear Customer,",
        "",
        "Thank you for writing in, and my apologies for the inconvenience caused.",
        "",
        "So that I can locate the exact record and give you an accurate update, could you "
        "please share the transaction reference number, the exact amount and date, and the "
        "account number the transaction was made from? Please do not share any password, "
        "OTP or card details with us.",
        "",
        "As soon as I have these details I will check this on priority and revert to you.",
        "",
        "Warm regards,",
        _SIGNOFF,
    ])
