"""Plain-SQL migrations: core first, then each enabled module's own folder."""

from collections.abc import Sequence
from pathlib import Path

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from coach.core.db import Connection, Pool

CORE_MIGRATIONS = Path(__file__).parent / "migrations"

type MigrationDir = tuple[str, Path]

# Supabase exposes the public schema over its REST API, so any table without RLS
# (including the checkpointer's own tables) would be readable with the anon key.
_ENABLE_RLS_EVERYWHERE = b"""
do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public' and not rowsecurity loop
    execute format('alter table public.%I enable row level security', t.tablename);
  end loop;
end $$;
"""


async def apply_migrations(conn: Connection, dirs: Sequence[MigrationDir]) -> list[str]:
    """Apply every ``*.sql`` file not yet recorded, directory by directory, in filename order.

    Returns the ids (``owner/filename``) applied by this call.
    """
    await conn.execute(
        "create table if not exists coach_migrations ("
        "id text primary key, applied_at timestamptz not null default now())"
    )
    applied: list[str] = []
    for owner, directory in dirs:
        for path in sorted(directory.glob("*.sql")):
            migration_id = f"{owner}/{path.name}"
            async with conn.transaction():
                cur = await conn.execute(
                    "insert into coach_migrations (id) values (%s) on conflict (id) do nothing",
                    (migration_id,),
                )
                if cur.rowcount == 0:
                    continue
                await conn.execute(path.read_bytes())
            applied.append(migration_id)
    return applied


async def migrate_all(pool: Pool, dirs: Sequence[MigrationDir]) -> list[str]:
    """Apply SQL migrations, create the LangGraph checkpoint tables, and enforce RLS."""
    async with pool.connection() as conn:
        applied = await apply_migrations(conn, dirs)
    await AsyncPostgresSaver(pool).setup()
    async with pool.connection() as conn:
        await conn.execute(_ENABLE_RLS_EVERYWHERE)
    return applied
