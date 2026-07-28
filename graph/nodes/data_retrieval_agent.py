"""Agent 4 - Data Retrieval Agent (Type 2 path, only reached when can_serve is True).

Stands in for a core-banking / SWIFT gateway lookup. Resolves the extracted entities to a
row in `transactions`, in strict priority order:
    1. reference_no   - exact, unique, the strongest identifier
    2. swift_ref      - exact, unique to cross-border transactions
    3. customer + type (+ amount) - a fuzzier fallback, most recent first
"""
from __future__ import annotations

import logging

from db.connection import get_conn
from graph.state import RMState

logger = logging.getLogger(__name__)


def _query(sql: str, params: list) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None


_SELECT = """
    SELECT t.*, c.name AS customer_name, c.account_number, c.kyc_status
    FROM transactions t
    JOIN customers c ON c.customer_id = t.customer_id
"""


def data_retrieval_agent(state: RMState) -> dict:
    entities = state.get("extracted_entities") or {}
    customer = state.get("customer_record")

    txn = None
    source = ""

    if reference := entities.get("reference_no"):
        txn = _query(_SELECT + " WHERE upper(t.reference_no) = upper(%s)", [reference])
        source = f"transactions.reference_no = {reference}"

    if txn is None and (swift := entities.get("swift_ref")):
        txn = _query(
            _SELECT + " WHERE upper(t.swift_ref) = upper(%s) OR upper(t.reference_no) = upper(%s)",
            [swift, swift],
        )
        source = f"transactions.swift_ref = {swift}"

    # Customer + type + amount. The amount is required, not optional: matching on customer
    # and type alone would return an arbitrary recent transaction the customer never asked
    # about. auth_agent enforces the same rule before letting a request reach this node.
    if txn is None and customer and entities.get("txn_type") and entities.get("amount"):
        txn = _query(
            _SELECT + " WHERE t.customer_id = %s AND t.type = %s AND t.amount = %s"
                      " ORDER BY t.initiated_at DESC LIMIT 1",
            [customer["customer_id"], entities["txn_type"], entities["amount"]],
        )
        source = (
            f"transactions by customer_id = {customer['customer_id']}, "
            f"type = {entities['txn_type']}, amount = {entities['amount']}"
        )

    if txn is None:
        # Reachable despite can_serve=True: the auth agent's existence check is a cheap OR
        # across identifiers, while this resolves a single specific row. The drafter
        # handles it by falling through to the "need more info" variant.
        logger.info("No transaction resolved for email %s despite can_serve=True", state.get("email_id"))
        return {
            "retrieved_data": None,
            "data_found": False,
            "data_source": source or "transactions (no usable identifier)",
            "agent_path": ["data_retrieval_agent"],
        }

    return {
        "retrieved_data": txn,
        "data_found": True,
        "data_source": source,
        "agent_path": ["data_retrieval_agent"],
    }
