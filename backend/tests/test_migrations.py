from pathlib import Path

import pytest

from coach.core.db import Connection, Pool
from coach.core.migrations import CORE_MIGRATIONS, migrate_all

pytestmark = pytest.mark.anyio


async def test_migrations_are_idempotent(pool: Pool) -> None:
    assert await migrate_all(pool, [("core", CORE_MIGRATIONS)]) == []


async def test_every_public_table_has_row_level_security(conn: Connection) -> None:
    cur = await conn.execute(
        "select tablename from pg_tables where schemaname = 'public' and not rowsecurity"
    )
    assert await cur.fetchall() == []


async def test_notes_embedding_matches_voyage_dimension(conn: Connection) -> None:
    cur = await conn.execute(
        "select atttypmod from pg_attribute "
        "where attrelid = 'public.notes'::regclass and attname = 'embedding'"
    )
    assert await cur.fetchone() == {"atttypmod": 1024}


async def test_anonymous_role_cannot_read_athletes(conn: Connection) -> None:
    await conn.execute("insert into athletes (name, telegram_chat_id) values ('Hidden', 999000111)")
    await conn.execute("set local role anon")

    cur = await conn.execute("select * from athletes")

    assert await cur.fetchall() == []


async def test_module_migrations_run_after_core(pool: Pool, tmp_path: Path) -> None:
    (tmp_path / "0001_fake.sql").write_text("create table fake_module_rows (id int primary key);")
    try:
        applied = await migrate_all(pool, [("core", CORE_MIGRATIONS), ("fake", tmp_path)])
        assert applied == ["fake/0001_fake.sql"]
    finally:
        async with pool.connection() as conn:
            await conn.execute("drop table if exists fake_module_rows")
            await conn.execute("delete from coach_migrations where id = 'fake/0001_fake.sql'")
