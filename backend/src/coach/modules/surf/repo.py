"""SQL for the surf tables."""

from datetime import datetime
from typing import Any
from uuid import UUID

from coach.core.db import Connection
from coach.core.models import Athlete


async def surf_sessions(
    conn: Connection, athlete: Athlete, *, since: datetime, spot_id: UUID | None = None
) -> list[dict[str, Any]]:
    """Surf sessions since a moment with their details, newest first, times local."""
    cur = await conn.execute(
        "select s.id, (s.started_at at time zone %(tz)s) as started_at, s.duration_min, "
        "sp.name as spot, d.wave_height_min_ft, d.wave_height_max_ft, d.wind, d.tide, "
        "d.waves_caught, d.board from sessions s "
        "join surf_details d on d.session_id = s.id "
        "left join surf_spots sp on sp.id = d.spot_id "
        "where s.athlete_id = %(athlete_id)s and s.started_at >= %(since)s "
        "and (%(spot_id)s::uuid is null or d.spot_id = %(spot_id)s) "
        "order by s.started_at desc",
        {"tz": athlete.timezone, "athlete_id": athlete.id, "since": since, "spot_id": spot_id},
    )
    return await cur.fetchall()


async def insert_details(conn: Connection, session_id: UUID, details: dict[str, Any]) -> None:
    """The surf part of a logged session."""
    await conn.execute(
        "insert into surf_details (session_id, spot_id, wave_height_min_ft, wave_height_max_ft, "
        "wind, tide, waves_caught, board, notes) values (%(session_id)s, %(spot_id)s, "
        "%(wave_height_min_ft)s, %(wave_height_max_ft)s, %(wind)s, %(tide)s, %(waves_caught)s, "
        "%(board)s, %(notes)s)",
        {"session_id": session_id, **details},
    )
