import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from coach.core.db import Connection, Pool
from coach.core.models import AgentRun, Athlete
from coach.core.repo import (
    claim_update,
    create_athlete,
    get_athlete_by_chat_id,
    recent_sessions,
    record_agent_run,
    sessions_per_discipline,
    weekly_load,
)
from tests.factories import insert_session, new_chat_id, new_update_id

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


async def test_finds_athlete_by_chat_id(conn: Connection) -> None:
    chat_id = new_chat_id()
    created = await create_athlete(conn, name="Jean", telegram_chat_id=chat_id)

    assert await get_athlete_by_chat_id(conn, chat_id) == created
    assert created.timezone == "Australia/Brisbane"
    assert await get_athlete_by_chat_id(conn, new_chat_id()) is None


async def test_claim_update_only_succeeds_once(conn: Connection) -> None:
    update_id = new_update_id()

    assert await claim_update(conn, update_id) is True
    assert await claim_update(conn, update_id) is False


async def test_concurrent_claims_have_exactly_one_winner(pool: Pool) -> None:
    update_id = new_update_id()

    async def claim() -> bool:
        async with pool.connection() as connection:
            return await claim_update(connection, update_id)

    results = await asyncio.gather(*(claim() for _ in range(4)))

    assert sorted(results) == [False, False, False, True]


async def test_history_queries_only_see_this_athlete_and_window(conn: Connection) -> None:
    me = await create_athlete(conn, name="Me", telegram_chat_id=new_chat_id())
    other = await create_athlete(conn, name="Other", telegram_chat_id=new_chat_id())
    await insert_session(conn, me, started_at=NOW - timedelta(days=1), duration_min=90, rpe=7)
    await insert_session(conn, me, started_at=NOW - timedelta(days=40))
    await insert_session(conn, other, started_at=NOW - timedelta(days=1))
    since = NOW - timedelta(days=14)

    per_discipline = await sessions_per_discipline(conn, me, since=since, until=NOW)
    recent = await recent_sessions(conn, me, since=since, until=NOW)

    assert per_discipline == [{"discipline": "testsport", "sessions": 1, "minutes": 90}]
    assert [r["duration_min"] for r in recent] == [90]


async def test_weekly_load_uses_the_athletes_local_week(conn: Connection) -> None:
    me = await create_athlete(conn, name="Me", telegram_chat_id=new_chat_id())
    # Sunday 22:00 in Brisbane (UTC+10) belongs to the week starting Monday 28 Sep.
    await insert_session(
        conn, me, started_at=datetime(2026, 10, 4, 12, 0, tzinfo=UTC), duration_min=60, rpe=5
    )
    # Monday 05:00 in Brisbane is still Sunday in UTC, but it starts the local week of 5 Oct.
    await insert_session(
        conn, me, started_at=datetime(2026, 10, 4, 19, 0, tzinfo=UTC), duration_min=60, rpe=7
    )

    weeks = await weekly_load(conn, me, since=NOW - timedelta(days=14), until=NOW)

    assert weeks == [
        {"week_start": date(2026, 9, 28), "sessions": 1, "minutes": 60, "load": 300},
        {"week_start": date(2026, 10, 5), "sessions": 1, "minutes": 60, "load": 420},
    ]


async def test_records_an_agent_run(conn: Connection, athlete: Athlete) -> None:
    run = AgentRun(
        athlete_id=athlete.id,
        trigger="message",
        input="hi",
        output="hello",
        model="test-model",
        latency_ms=12,
        tool_calls=[{"tool": "query_history", "module": "core", "args": {"kind": "weekly_load"}}],
        input_tokens=10,
        output_tokens=3,
    )

    run_id = await record_agent_run(conn, run)

    cur = await conn.execute("select * from agent_runs where id = %s", (run_id,))
    row = await cur.fetchone()
    assert row is not None
    assert row["tool_calls"][0]["tool"] == "query_history"
    assert (row["input_tokens"], row["output_tokens"], row["error"]) == (10, 3, None)


async def test_recent_sessions_report_local_time_and_weekday(conn: Connection) -> None:
    me = await create_athlete(conn, name="Me", telegram_chat_id=new_chat_id())
    # 19:00 UTC on Sunday is 05:00 on Monday in Brisbane.
    await insert_session(conn, me, started_at=datetime(2026, 10, 4, 19, 0, tzinfo=UTC))

    [session] = await recent_sessions(conn, me, since=NOW - timedelta(days=7), until=NOW)

    assert session["started_at"] == datetime(2026, 10, 5, 5, 0)
    assert session["weekday"] == "Monday"


async def test_history_excludes_sessions_after_until(conn: Connection) -> None:
    me = await create_athlete(conn, name="Me", telegram_chat_id=new_chat_id())
    await insert_session(conn, me, started_at=NOW - timedelta(days=1))

    rows = await sessions_per_discipline(
        conn, me, since=NOW - timedelta(days=7), until=NOW - timedelta(days=2)
    )

    assert rows == []
