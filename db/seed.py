"""Creates the `hdfc_rm` database, schema, and synthetic data. Safe to rerun any time —
drops and recreates the database from scratch (wipes prior rm_responses/audit history).

Usage: python -m db.seed
"""
from __future__ import annotations

from pathlib import Path

import psycopg

from config.settings import settings
from db import seed_data as sd

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

PRIMARY_KEY_COLUMNS = {
    "products": "product_id",
    "customers": "customer_id",
    "emails": "email_id",
    "transactions": "txn_id",
    "rm_responses": "response_id",
    "rm_audit_log": "audit_id",
}

TABLES = list(PRIMARY_KEY_COLUMNS)


def recreate_database() -> None:
    db_name = settings.database_name
    with psycopg.connect(settings.admin_database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Drop fails with "database is being accessed by other users" if a previous
            # Streamlit run still holds the checkpointer connection open.
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (db_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            cur.execute(f'CREATE DATABASE "{db_name}"')
    print(f"Recreated database: {db_name}")


def create_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_PATH.read_text())
    print(f"Created schema ({len(TABLES)} tables).")


def insert_rows(conn: psycopg.Connection, table: str, rows: list[dict]) -> list[int]:
    """Inserts rows and returns the generated primary keys, in input order."""
    if not rows:
        return []
    columns = list(rows[0].keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(f"%({c})s" for c in columns)
    id_column = PRIMARY_KEY_COLUMNS[table]
    query = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) RETURNING {id_column}"
    ids = []
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(query, row)
            ids.append(cur.fetchone()[id_column])
    return ids


def resolve_fk(rows: list[dict], field: str, id_map: list[int]) -> list[dict]:
    """Remaps a 1-based index in `field` to the real serial ID at that position."""
    out = []
    for row in rows:
        row = dict(row)
        row[field] = id_map[row[field] - 1]
        out.append(row)
    return out


def load_data(conn: psycopg.Connection) -> None:
    insert_rows(conn, "products", sd.PRODUCTS)
    customer_ids = insert_rows(conn, "customers", sd.CUSTOMERS)
    insert_rows(conn, "transactions", resolve_fk(sd.TRANSACTIONS, "customer_id", customer_ids))
    insert_rows(conn, "emails", sd.EMAILS)
    conn.commit()
    print("Loaded seed data.")


def print_row_counts(conn: psycopg.Connection) -> None:
    print("\nRow counts:")
    with conn.cursor() as cur:
        for table in TABLES:
            cur.execute(f"SELECT count(*) AS n FROM {table}")
            print(f"  {table:<16} {cur.fetchone()['n']}")


def setup_checkpointer() -> None:
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(settings.database_url) as saver:
        saver.setup()
    print("\nLangGraph checkpoint tables ready.")


def main() -> None:
    sd.validate()
    print("Seed data validated.")
    recreate_database()
    with psycopg.connect(settings.database_url, row_factory=psycopg.rows.dict_row) as conn:
        create_schema(conn)
        load_data(conn)
        print_row_counts(conn)
    setup_checkpointer()
    print("\nSeed complete.")


if __name__ == "__main__":
    main()
