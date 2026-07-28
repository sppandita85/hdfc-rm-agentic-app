"""Postgres connection helper for the `hdfc_rm` app database (not the checkpointer)."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from config.settings import settings


class DatabaseUnavailable(RuntimeError):
    """Raised when Postgres can't be reached, so the UI can show a friendly banner
    naming the service instead of leaking a psycopg stack trace at the RM."""


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    try:
        conn = psycopg.connect(settings.database_url, row_factory=dict_row)
    except psycopg.OperationalError as exc:
        raise DatabaseUnavailable(
            f"Cannot reach Postgres at {settings.database_url}. "
            "Is the `postgres` container running, and has `python -m db.seed` been run?"
        ) from exc

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
