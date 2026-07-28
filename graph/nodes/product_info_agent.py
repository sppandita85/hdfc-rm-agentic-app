"""Agent 2 - Product Info Agent (Type 1 path).

Retrieves the products most relevant to the customer's question from the `products` table.

Matching is plain SQL keyword and category scoring — no embeddings or pgvector. With a
15-row catalogue and a small, well-known category vocabulary, a scored ILIKE beats a vector
index on both accuracy and explainability, and the RM can see exactly why a product matched.
"""
from __future__ import annotations

import logging
import re

from db.connection import get_conn
from graph.state import RMState

logger = logging.getLogger(__name__)

MAX_PRODUCTS = 3

# Phrases a customer is likely to use, mapped to the catalogue's `category` values.
# Order matters: the first match on a longer, more specific phrase wins.
_CATEGORY_HINTS: list[tuple[str, str]] = [
    ("tax saver", "fixed_deposit"),
    ("senior citizen", "fixed_deposit"),
    ("fixed deposit", "fixed_deposit"),
    (" fd", "fixed_deposit"),
    ("term deposit", "fixed_deposit"),
    ("recurring deposit", "recurring_deposit"),
    (" rd", "recurring_deposit"),
    ("home loan", "home_loan"),
    ("housing loan", "home_loan"),
    ("personal loan", "personal_loan"),
    ("car loan", "car_loan"),
    ("vehicle loan", "car_loan"),
    ("education loan", "education_loan"),
    ("student loan", "education_loan"),
    ("credit card", "credit_card"),
    ("regalia", "credit_card"),
    ("moneyback", "credit_card"),
    ("demat", "demat"),
    ("trading account", "demat"),
    ("nre", "nri"),
    ("nro", "nri"),
    ("non-resident", "nri"),
    ("current account", "current"),
    ("business account", "current"),
    ("salary account", "salary"),
    ("savings", "savings"),
    ("savingsmax", "savings"),
]

_STOPWORDS = {
    "the", "and", "for", "you", "your", "what", "with", "have", "this", "that", "would",
    "like", "please", "hello", "hi", "dear", "thanks", "thank", "regards", "could", "can",
    "about", "from", "are", "any", "all", "how", "does", "want", "need", "know", "there",
    "will", "was", "not", "but", "out", "get", "sir", "madam", "team", "also",
}


def _detect_categories(text: str) -> list[str]:
    found: list[str] = []
    for phrase, category in _CATEGORY_HINTS:
        if phrase in text and category not in found:
            found.append(category)
    return found


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[a-z]{4,}", text)
    seen: list[str] = []
    for word in words:
        if word not in _STOPWORDS and word not in seen:
            seen.append(word)
    return seen[:12]


def product_info_agent(state: RMState) -> dict:
    text = f"{state.get('subject', '')}\n{state.get('body', '')}".lower()
    categories = _detect_categories(text)
    keywords = _keywords(text)

    # Score every product: a category hit is worth far more than a loose word match, so
    # "what are your FD rates" can never be outranked by a product that merely repeats a
    # common word from the email.
    sql = """
        SELECT *,
               (CASE WHEN category = ANY(%(categories)s) THEN 10 ELSE 0 END)
             + (SELECT count(*) FROM unnest(%(keywords)s::text[]) AS kw
                 WHERE name ILIKE '%%' || kw || '%%'
                    OR description ILIKE '%%' || kw || '%%'
                    OR array_to_string(key_features, ' ') ILIKE '%%' || kw || '%%')
               AS match_score
        FROM products
        ORDER BY match_score DESC, product_id
        LIMIT %(limit)s
    """

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {"categories": categories or [""], "keywords": keywords or [""], "limit": MAX_PRODUCTS})
                rows = [dict(r) for r in cur.fetchall()]
    except Exception:
        logger.warning("Product lookup failed for email %s", state.get("email_id"), exc_info=True)
        return {
            "retrieved_data": None,
            "data_found": False,
            "data_source": "products (lookup failed)",
            "agent_path": ["product_info_agent"],
        }

    # A score of 0 across the board means nothing actually matched and the ORDER BY just
    # returned the lowest product_ids — that is not a retrieval result, so drop it rather
    # than feeding arbitrary products to the drafter.
    matched = [r for r in rows if r["match_score"] > 0]

    return {
        "retrieved_data": matched or None,
        "data_found": bool(matched),
        "data_source": (
            f"products (matched categories: {', '.join(categories) or 'none'})"
        ),
        "agent_path": ["product_info_agent"],
    }
