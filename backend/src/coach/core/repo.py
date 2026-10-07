"""SQL for the core tables. Every function takes an open connection; callers own transactions."""

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import AsyncCursor
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from coach.core.config import DEFAULT_TIMEZONE
from coach.core.db import Connection
from coach.core.models import AgentRun, Athlete


async def _one(cur: AsyncCursor[DictRow]) -> DictRow:
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError("query returned no row")
    return row


def _athlete(row: DictRow) -> Athlete:
    return Athlete(
        id=row["id"],
        name=row["name"],
        timezone=row["timezone"],
        telegram_chat_id=row["telegram_chat_id"],
    )


async def create_athlete(
    conn: Connection, *, name: str, telegram_chat_id: int | None, timezone: str = DEFAULT_TIMEZONE
) -> Athlete:
    """Insert an athlete and return it."""
    cur = await conn.execute(
        "insert into athletes (name, telegram_chat_id, timezone) values (%s, %s, %s) "
        "returning id, name, timezone, telegram_chat_id",
        (name, telegram_chat_id, timezone),
    )
    return _athlete(await _one(cur))


async def get_athlete_by_chat_id(conn: Connection, chat_id: int) -> Athlete | None:
    """The athlete linked to a Telegram chat, if any."""
    cur = await conn.execute(
        "select id, name, timezone, telegram_chat_id from athletes where telegram_chat_id = %s",
        (chat_id,),
    )
    row = await cur.fetchone()
    return _athlete(row) if row else None


async def claim_update(conn: Connection, update_id: int) -> bool:
    """Record a Telegram update id; True only the first time, so retries become no-ops."""
    cur = await conn.execute(
        "insert into processed_updates (update_id) values (%s) on conflict (update_id) do nothing",
        (update_id,),
    )
    return cur.rowcount == 1


async def recent_sessions(
    conn: Connection, athlete: Athlete, *, since: datetime, until: datetime, limit: int = 50
) -> list[dict[str, Any]]:
    """Sessions in ``[since, until)``, newest first, with local start time and weekday."""
    cur = await conn.execute(
        "select discipline, started_at at time zone %(tz)s as started_at, "
        "to_char(started_at at time zone %(tz)s, 'FMDay') as weekday, "
        "duration_min, rpe, summary from sessions "
        "where athlete_id = %(athlete_id)s "
        "and started_at >= %(since)s and started_at < %(until)s "
        "order by sessions.started_at desc limit %(limit)s",
        {
            "tz": athlete.timezone,
            "athlete_id": athlete.id,
            "since": since,
            "until": until,
            "limit": limit,
        },
    )
    return await cur.fetchall()


async def sessions_per_discipline(
    conn: Connection, athlete: Athlete, *, since: datetime, until: datetime
) -> list[dict[str, Any]]:
    """Session count and minutes per discipline in ``[since, until)``."""
    cur = await conn.execute(
        "select discipline, count(*)::int as sessions, "
        "coalesce(sum(duration_min), 0)::int as minutes from sessions "
        "where athlete_id = %(athlete_id)s "
        "and started_at >= %(since)s and started_at < %(until)s "
        "group by discipline order by discipline",
        {"athlete_id": athlete.id, "since": since, "until": until},
    )
    return await cur.fetchall()


async def weekly_load(
    conn: Connection, athlete: Athlete, *, since: datetime, until: datetime
) -> list[dict[str, Any]]:
    """Sessions, minutes and load (minutes x RPE) per local week in ``[since, until)``."""
    cur = await conn.execute(
        "select (date_trunc('week', started_at at time zone %(tz)s))::date as week_start, "
        "count(*)::int as sessions, coalesce(sum(duration_min), 0)::int as minutes, "
        "coalesce(sum(duration_min * rpe), 0)::int as load from sessions "
        "where athlete_id = %(athlete_id)s "
        "and started_at >= %(since)s and started_at < %(until)s "
        "group by 1 order by 1",
        {"tz": athlete.timezone, "athlete_id": athlete.id, "since": since, "until": until},
    )
    return await cur.fetchall()


async def record_agent_run(conn: Connection, run: AgentRun) -> UUID:
    """Store one agent turn for the trace viewer and evals."""
    cur = await conn.execute(
        "insert into agent_runs (athlete_id, trigger, input, tool_calls, output, model, "
        "input_tokens, output_tokens, latency_ms, error) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (
            run.athlete_id,
            run.trigger,
            run.input,
            Jsonb(run.tool_calls),
            run.output,
            run.model,
            run.input_tokens,
            run.output_tokens,
            run.latency_ms,
            run.error,
        ),
    )
    run_id: UUID = (await _one(cur))["id"]
    return run_id


async def create_session(
    conn: Connection,
    athlete: Athlete,
    *,
    discipline: str,
    started_at: datetime,
    duration_min: int | None = None,
    rpe: int | None = None,
    summary: str | None = None,
    input_type: str = "text",
    call_id: str | None = None,
) -> UUID:
    """Insert one training session in any discipline; ``call_id`` is the tool call writing it."""
    cur = await conn.execute(
        "insert into sessions (athlete_id, discipline, started_at, duration_min, rpe, summary, "
        "input_type, source_call_id) values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (athlete.id, discipline, started_at, duration_min, rpe, summary, input_type, call_id),
    )
    session_id: UUID = (await _one(cur))["id"]
    return session_id


async def undo_session(conn: Connection, athlete: Athlete, session_id: UUID) -> str | None:
    """Delete one of this athlete's sessions; module rows go with it through foreign keys."""
    cur = await conn.execute(
        "delete from sessions where id = %s and athlete_id = %s returning summary",
        (session_id, athlete.id),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return str(row["summary"] or "a session")


async def session_for_call(conn: Connection, athlete: Athlete, call_id: str | None) -> UUID | None:
    """The session a tool call already wrote, if it runs again (e.g. on an interrupt resume)."""
    if not call_id:
        return None
    cur = await conn.execute(
        "select id from sessions where athlete_id = %s and source_call_id = %s",
        (athlete.id, call_id),
    )
    row = await cur.fetchone()
    return row["id"] if row else None
