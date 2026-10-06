import os
from collections.abc import AsyncIterator

import pytest
from psycopg_pool import PoolTimeout

from coach.core.db import Connection, Pool, create_pool
from coach.core.migrations import CORE_MIGRATIONS, migrate_all
from coach.core.models import Athlete
from coach.core.repo import create_athlete
from tests.factories import new_chat_id

TEST_DATABASE_URL = os.environ.get(
    "COACH_TEST_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54422/postgres"
)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
async def pool() -> AsyncIterator[Pool]:
    pool = create_pool(TEST_DATABASE_URL)
    try:
        await pool.open(wait=True, timeout=10)
    except PoolTimeout:
        pytest.fail("No test database. Start it with `supabase db start` from the repo root.")
    await migrate_all(pool, [("core", CORE_MIGRATIONS)])
    async with pool.connection() as conn:
        await conn.execute(
            "truncate athletes, processed_updates, eval_cases, eval_runs, "
            "checkpoints, checkpoint_writes, checkpoint_blobs cascade"
        )
        await conn.execute(
            "insert into disciplines (name, label) values ('testsport', 'Test sport') "
            "on conflict (name) do nothing"
        )
    yield pool
    await pool.close()


@pytest.fixture
async def conn(pool: Pool) -> AsyncIterator[Connection]:
    async with pool.connection() as connection, connection.transaction(force_rollback=True):
        yield connection


@pytest.fixture
async def athlete(pool: Pool) -> Athlete:
    async with pool.connection() as connection:
        return await create_athlete(connection, name="Test Athlete", telegram_chat_id=new_chat_id())
