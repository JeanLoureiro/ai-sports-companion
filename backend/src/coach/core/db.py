"""Postgres connection pool shared by the app, the agent tools and the checkpointer."""

from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

type Connection = AsyncConnection[DictRow]
type Pool = AsyncConnectionPool[AsyncConnection[DictRow]]


def create_pool(database_url: str, *, max_size: int = 4) -> Pool:
    """Create an unopened pool; callers ``await pool.open()``.

    Autocommit and dict rows are what the LangGraph checkpointer requires.
    Prepared statements are off because Supabase's transaction pooler cannot keep them.
    """
    return AsyncConnectionPool(
        conninfo=database_url,
        connection_class=AsyncConnection[DictRow],
        kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
        min_size=1,
        max_size=max_size,
        open=False,
    )
