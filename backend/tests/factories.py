"""Row builders for tests."""

import secrets
from datetime import datetime
from uuid import UUID

from coach.core.db import Connection
from coach.core.models import Athlete


def new_chat_id() -> int:
    return secrets.randbelow(10**12) + 1


def new_update_id() -> int:
    return secrets.randbelow(10**15) + 1


async def insert_session(
    conn: Connection,
    athlete: Athlete,
    *,
    started_at: datetime,
    discipline: str = "testsport",
    duration_min: int = 60,
    rpe: int = 6,
) -> UUID:
    cur = await conn.execute(
        "insert into sessions (athlete_id, discipline, started_at, duration_min, rpe) "
        "values (%s, %s, %s, %s, %s) returning id",
        (athlete.id, discipline, started_at, duration_min, rpe),
    )
    row = await cur.fetchone()
    assert row is not None
    session_id: UUID = row["id"]
    return session_id
