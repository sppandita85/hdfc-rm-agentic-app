"""Query helpers: inbox reads for the dashboard, and the RM-action writes."""
from __future__ import annotations

from db.connection import get_conn


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def list_emails() -> list[dict]:
    """Inbox, newest first, with the sender resolved against `customers` where possible."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.*,
                       c.customer_id, c.name AS customer_name, c.account_number,
                       c.phone, c.kyc_status,
                       r.rm_action, r.final_text
                FROM emails e
                LEFT JOIN customers c ON lower(c.email) = lower(e.customer_email)
                LEFT JOIN rm_responses r ON r.email_id = e.email_id
                ORDER BY e.received_at DESC
                """
            )
            return [dict(r) for r in cur.fetchall()]


def get_email(email_id: int) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.*,
                       c.customer_id, c.name AS customer_name, c.account_number,
                       c.phone, c.kyc_status
                FROM emails e
                LEFT JOIN customers c ON lower(c.email) = lower(e.customer_email)
                WHERE e.email_id = %s
                """,
                (email_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_response(email_id: int) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM rm_responses WHERE email_id = %s", (email_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def status_counts() -> dict[str, int]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, count(*) AS n FROM emails GROUP BY status")
            return {r["status"]: r["n"] for r in cur.fetchall()}


def list_audit_log(limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.*, e.subject, e.customer_email
                FROM rm_audit_log a
                JOIN emails e ON e.email_id = a.email_id
                ORDER BY a.occurred_at DESC, a.audit_id DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]


def list_responses() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.*, e.subject, e.customer_email, e.intent_type
                FROM rm_responses r
                JOIN emails e ON e.email_id = r.email_id
                ORDER BY r.edited_at DESC
                """
            )
            return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
def record_audit(email_id: int, action: str, detail: str | None = None, actor: str = "RM") -> None:
    """Appends to the audit trail. Separate from record_rm_action so the UI can also log
    non-decision events (processed, regenerated)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO rm_audit_log (email_id, action, detail, actor) VALUES (%s, %s, %s, %s)",
            (email_id, action, detail, actor),
        )


def record_rm_action(
    email_id: int,
    draft_text: str,
    rm_action: str,
    final_text: str | None = None,
    detail: str | None = None,
) -> None:
    """Persists the RM's decision and marks the email answered, in one transaction.

    `rm_responses` is upserted (one row per email, holding the current decision) while
    `rm_audit_log` gets an append — so a reject that is later regenerated and accepted
    leaves both a correct current state and a full history.
    """
    if rm_action not in ("accepted", "rejected", "edited"):
        raise ValueError(f"Unknown rm_action: {rm_action}")

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO rm_responses (email_id, draft_text, final_text, rm_action, edited_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (email_id) DO UPDATE
                SET draft_text = EXCLUDED.draft_text,
                    final_text = EXCLUDED.final_text,
                    rm_action  = EXCLUDED.rm_action,
                    edited_at  = now()
            """,
            (email_id, draft_text, final_text, rm_action),
        )
        conn.execute("UPDATE emails SET status = 'answered' WHERE email_id = %s", (email_id,))
        conn.execute(
            "INSERT INTO rm_audit_log (email_id, action, detail) VALUES (%s, %s, %s)",
            (email_id, rm_action, detail),
        )


def reset_email_status(email_id: int) -> None:
    """Used by 'Regenerate draft' so an email that was already answered goes back to the
    processing state and the inbox badge stops claiming it is done."""
    with get_conn() as conn:
        conn.execute("UPDATE emails SET status = 'processing' WHERE email_id = %s", (email_id,))
