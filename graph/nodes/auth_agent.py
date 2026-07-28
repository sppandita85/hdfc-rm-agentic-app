"""Agent 3 - Authentication Agent (Type 2 path).

======================================================================================
STUB - THERE IS NO REAL AUTHENTICATION HERE. THIS IS A PASS-THROUGH BY DESIGN.
======================================================================================
This node does NOT verify that the sender is who they claim to be. It only answers a
narrower, mechanical question: *can this request be served at all?* — i.e. did the email
carry a usable identifier, and does a matching record actually exist?

A production implementation would, at this point, perform real identity verification
before any customer data is read: OTP to the registered mobile, knowledge-based
authentication, a signed session token from the customer portal, or a callback to the
RM. It would also enforce that the resolved customer owns the referenced transaction,
and would refuse to proceed on an expired KYC.

# TODO(real-auth): replace the can_serve heuristic below with genuine identity
# verification. The state interface (`can_serve`, `auth_reason`, `customer_record`,
# `extracted_entities`) is intentionally kept stable so that logic can be dropped in
# here without reshaping the graph or touching any other node.

Every decision this node makes is logged, so the "auth check" is at least observable.
"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from db.connection import get_conn
from graph.state import RMState
from llm import entity_prompts
from llm.json_parsing import extract_json
from llm.ollama_client import get_llm

logger = logging.getLogger(__name__)


def _extract_entities(subject: str, body: str) -> dict:
    """LLM extraction for the soft fields, regex for the identifier-shaped ones."""
    llm_entities = None
    try:
        response = get_llm().invoke([
            SystemMessage(content=entity_prompts.SYSTEM_PROMPT),
            HumanMessage(content=entity_prompts.build_user_prompt(subject, body)),
        ])
        llm_entities = extract_json(response.content)
    except Exception:
        logger.warning("Ollama call failed during entity extraction; using regex only.", exc_info=True)

    return entity_prompts.merge_entities(llm_entities, entity_prompts.extract_by_regex(subject, body))


def _lookup_customer(sender_email: str, account_number: str | None) -> dict | None:
    """Resolves who is asking, by sender address first and quoted account number second."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM customers WHERE lower(email) = lower(%s)", (sender_email,))
            if row := cur.fetchone():
                return dict(row)
            if account_number:
                cur.execute("SELECT * FROM customers WHERE account_number = %s", (account_number,))
                if row := cur.fetchone():
                    return dict(row)
    return None


def _record_exists(entities: dict, customer: dict | None) -> bool:
    """True if a *specific* transaction can be located from what we extracted."""
    clauses = []
    params: list = []

    if entities.get("reference_no"):
        clauses.append("upper(reference_no) = upper(%s)")
        params.append(entities["reference_no"])
    if entities.get("swift_ref"):
        clauses.append("upper(swift_ref) = upper(%s)")
        params.append(entities["swift_ref"])
        # A SWIFT reference in the email may also be quoted as the primary reference.
        clauses.append("upper(reference_no) = upper(%s)")
        params.append(entities["swift_ref"])

    if not clauses and _has_narrowing_pair(entities, customer):
        clauses.append("(customer_id = %s AND type = %s AND amount = %s)")
        params.extend([customer["customer_id"], entities["txn_type"], entities["amount"]])

    if not clauses:
        return False

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT 1 FROM transactions WHERE {' OR '.join(clauses)} LIMIT 1",
                params,
            )
            return cur.fetchone() is not None


def _has_narrowing_pair(entities: dict, customer: dict | None) -> bool:
    """Whether a known customer plus a transaction type AND amount is enough to go on.

    A transaction type on its own is deliberately NOT enough. A vague email like "I sent
    some money and it hasn't arrived" is enough for the model to infer txn_type='transfer',
    and matching on customer + type alone would then pull that customer's most recent
    transfer and report on it confidently — answering about a transaction the customer
    never asked about. Requiring the amount as well makes the match specific to a record
    the customer actually described.
    """
    return bool(customer and entities.get("txn_type") and entities.get("amount"))


def auth_agent(state: RMState) -> dict:
    subject = state.get("subject", "")
    body = state.get("body", "")
    sender = state.get("customer_email", "")

    entities = _extract_entities(subject, body)

    try:
        customer = _lookup_customer(sender, entities.get("account_number"))
        exists = _record_exists(entities, customer)
    except Exception:
        logger.warning("Auth lookup failed for email %s", state.get("email_id"), exc_info=True)
        return {
            "extracted_entities": entities,
            "customer_record": None,
            "can_serve": False,
            "auth_reason": "Could not reach the banking system to verify this request.",
            "agent_path": ["auth_agent"],
        }

    # Only a reference number identifies a *transaction*. An account number identifies the
    # *customer*, which is why it is used for resolution above but not counted here.
    has_txn_identifier = bool(entities.get("reference_no") or entities.get("swift_ref"))

    if not has_txn_identifier and not _has_narrowing_pair(entities, customer):
        if customer is None:
            can_serve, reason = False, (
                f"Sender {sender} does not match any customer on record, and the email quotes "
                "no transaction reference to search by."
            )
        else:
            can_serve, reason = False, (
                "The email does not quote a transaction reference, nor a transaction type and "
                "amount specific enough to identify a single record."
            )
    elif not exists:
        can_serve, reason = False, (
            "No matching record was found in the banking system for the details provided."
        )
    else:
        can_serve, reason = True, (
            "A matching record was located from the details provided"
            + (f" for customer {customer['name']}." if customer else " (sender not on record).")
        )

    # The "auth check" audit trail — see the stub note in the module docstring.
    logger.info(
        "AUTH CHECK email_id=%s sender=%s can_serve=%s customer=%s entities=%s reason=%s",
        state.get("email_id"), sender, can_serve,
        customer["customer_id"] if customer else None, entities, reason,
    )

    return {
        "extracted_entities": entities,
        "customer_record": customer,
        "can_serve": can_serve,
        "auth_reason": reason,
        "agent_path": ["auth_agent"],
    }


def route_by_auth(state: RMState) -> str:
    """Conditional edge: only serve a data lookup when the auth check cleared it.
    Otherwise skip retrieval entirely and let the drafter write a holding reply."""
    return "retrieve" if state.get("can_serve") else "draft"
