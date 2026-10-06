"""SQL for the gym tables."""

from datetime import datetime
from typing import Any
from uuid import UUID

from coach.core.db import Connection
from coach.core.models import Athlete


async def active_program(conn: Connection, athlete: Athlete) -> dict[str, Any] | None:
    """The athlete's active program, if any."""
    cur = await conn.execute(
        "select id, name, sessions_per_week_target from programs where athlete_id = %s and active",
        (athlete.id,),
    )
    return await cur.fetchone()


async def next_pending(
    conn: Connection, program_id: UUID, *, day_label: str | None = None
) -> dict[str, Any] | None:
    """The first session neither completed nor skipped, optionally for one day label."""
    cur = await conn.execute(
        "select id, position, week, day_label, label, planned_date from program_sessions "
        "where program_id = %(program_id)s and completed_session_id is null and not skipped "
        "and (%(day)s::text is null or day_label = %(day)s) order by position limit 1",
        {"program_id": program_id, "day": day_label},
    )
    return await cur.fetchone()


async def prescriptions(conn: Connection, program_session_id: UUID) -> list[dict[str, Any]]:
    """Every exercise of one session, in order."""
    cur = await conn.execute(
        "select pe.block, e.name as exercise, pe.sets, pe.reps, pe.rest_s, pe.tempo, pe.notes "
        "from program_exercises pe join exercises e on e.id = pe.exercise_id "
        "where pe.program_session_id = %s order by pe.position",
        (program_session_id,),
    )
    return await cur.fetchall()


async def progress(conn: Connection, program_id: UUID) -> dict[str, Any]:
    """How many sessions are done, skipped, and in total."""
    cur = await conn.execute(
        "select count(*) filter (where completed_session_id is not null)::int as done, "
        "count(*) filter (where skipped)::int as skipped, count(*)::int as total "
        "from program_sessions where program_id = %s",
        (program_id,),
    )
    row = await cur.fetchone()
    return dict(row) if row else {"done": 0, "skipped": 0, "total": 0}


async def done_since(conn: Connection, program_id: UUID, since: datetime) -> int:
    """Program sessions completed by sessions that started at or after ``since``."""
    cur = await conn.execute(
        "select count(*)::int as n from program_sessions ps "
        "join sessions s on s.id = ps.completed_session_id "
        "where ps.program_id = %s and s.started_at >= %s",
        (program_id, since),
    )
    row = await cur.fetchone()
    return int(row["n"]) if row else 0
