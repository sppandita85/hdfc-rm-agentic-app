"""Builds a process-lifetime PostgresSaver.

PostgresSaver.from_conn_string() is a @contextmanager that closes its connection when the
`with` block exits — unsuitable for a saver that must stay alive for the whole app process.
Instead we open the same kind of connection it would (autocommit, prepare_threshold=0,
dict_row) directly and keep it open ourselves. Callers (Streamlit via st.cache_resource, the
smoke test via a module-level singleton) are responsible for keeping the returned saver alive
for the process lifetime and not recreating it per call.

The checkpointer is used here purely as a cache: the graph has no interrupt, so its only job
is to make re-opening an already-processed email instant instead of re-running the LLM.
"""
from __future__ import annotations

from psycopg import Connection
from psycopg.rows import dict_row

from langgraph.checkpoint.postgres import PostgresSaver

from config.settings import settings


def build_checkpointer() -> PostgresSaver:
    conn = Connection.connect(
        settings.database_url,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    return PostgresSaver(conn)
