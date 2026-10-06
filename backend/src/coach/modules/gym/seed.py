"""Load a program file into the database: ``python -m coach.modules.gym.seed``."""

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from coach.core.config import get_settings
from coach.core.db import Connection, create_pool
from coach.core.models import Athlete
from coach.core.repo import get_athlete_by_chat_id
from coach.modules.gym.library import ExerciseIndex, library_index
from coach.modules.gym.program import ProgramDef, load_program


class ProgramConflictError(Exception):
    """The athlete already has an active program and ``replace`` was not given."""


async def _returning_id(conn: Connection, query: str, params: tuple[object, ...]) -> UUID:
    cur = await conn.execute(query, params)
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError("insert returned no row")
    row_id: UUID = row["id"]
    return row_id


async def _upsert_library(
    conn: Connection, athlete: Athlete, index: ExerciseIndex
) -> dict[str, UUID]:
    ids: dict[str, UUID] = {}
    for exercise in index:
        ids[exercise.name] = await _returning_id(
            conn,
            "insert into exercises (athlete_id, name, aliases, pattern, equipment, load_areas) "
            "values (%s, %s, %s, %s, %s, %s) on conflict (athlete_id, name) do update set "
            "aliases = excluded.aliases, pattern = excluded.pattern, "
            "equipment = excluded.equipment, load_areas = excluded.load_areas returning id",
            (
                athlete.id,
                exercise.name,
                list(exercise.aliases),
                exercise.pattern,
                list(exercise.equipment),
                list(exercise.load_areas),
            ),
        )
    return ids


async def seed_program(
    conn: Connection,
    athlete: Athlete,
    program: ProgramDef,
    index: ExerciseIndex,
    *,
    source_file: str,
    replace: bool = False,
) -> UUID:
    """Write the library and the program in one transaction; returns the new program id."""
    async with conn.transaction():
        cur = await conn.execute(
            "select id, source_file from programs where athlete_id = %s and active", (athlete.id,)
        )
        active = await cur.fetchone()
        if active is not None and not replace:
            raise ProgramConflictError(
                f"active program already seeded from {active['source_file']}; use --replace"
            )
        if active is not None:
            await conn.execute("update programs set active = false where id = %s", (active["id"],))
        ids = await _upsert_library(conn, athlete, index)
        program_id = await _returning_id(
            conn,
            "insert into programs (athlete_id, name, source_file, sessions_per_week_target) "
            "values (%s, %s, %s, %s) returning id",
            (athlete.id, program.name, source_file, program.sessions_per_week_target),
        )
        for position, session in enumerate(program.sessions, start=1):
            session_id = await _returning_id(
                conn,
                "insert into program_sessions (program_id, position, week, day_label, label) "
                "values (%s, %s, %s, %s, %s) returning id",
                (program_id, position, session.week, session.day, session.label),
            )
            for exercise_position, p in enumerate(session.exercises, start=1):
                exercise = index.resolve(p.exercise)
                if exercise is None:
                    raise ValueError(f"unknown exercise {p.exercise!r}")
                await conn.execute(
                    "insert into program_exercises (program_session_id, position, exercise_id, "
                    "block, sets, reps, rest_s, tempo, notes) "
                    "values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        session_id,
                        exercise_position,
                        ids[exercise.name],
                        p.block,
                        p.sets,
                        p.reps,
                        p.rest_s,
                        p.tempo,
                        p.notes,
                    ),
                )
    return program_id


async def _seed(path: Path, program: ProgramDef, chat_id: int, replace: bool) -> None:
    pool = create_pool(get_settings().database_url.get_secret_value())
    await pool.open()
    try:
        async with pool.connection() as conn:
            athlete = await get_athlete_by_chat_id(conn, chat_id)
            if athlete is None:
                raise SystemExit(f"No athlete for chat {chat_id}; run `coach add-athlete` first.")
            program_id = await seed_program(
                conn, athlete, program, library_index(), source_file=path.name, replace=replace
            )
        print(f"Seeded {program.name} for {athlete.name} ({program_id})")
    finally:
        await pool.close()


def main(argv: Sequence[str] | None = None) -> None:
    """Validate a program file and, unless ``--check``, seed it for an athlete."""
    parser = argparse.ArgumentParser(prog="python -m coach.modules.gym.seed")
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--chat-id", type=int)
    parser.add_argument("--replace", action="store_true", help="retire the active program")
    parser.add_argument("--check", action="store_true", help="validate only")
    args = parser.parse_args(argv)
    program = load_program(args.program, library_index())
    weeks = len({s.week for s in program.sessions})
    print(f"{program.name}: {len(program.sessions)} sessions over {weeks} weeks")
    if args.check:
        return
    if args.chat_id is None:
        parser.error("--chat-id is required unless --check")
    asyncio.run(_seed(args.program, program, args.chat_id, args.replace))


if __name__ == "__main__":
    main()
