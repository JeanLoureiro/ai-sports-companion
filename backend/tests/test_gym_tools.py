import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from coach.core.context import CoachContext
from coach.core.db import Pool
from coach.core.graph import build_graph
from coach.core.models import Athlete
from coach.core.registry import Registry
from coach.core.repo import create_session
from coach.modules.gym.library import library_index
from coach.modules.gym.module import GymModule
from coach.modules.gym.program import load_program
from coach.modules.gym.seed import seed_program
from tests.fakes import scripted

pytestmark = pytest.mark.anyio

SAMPLE = Path(__file__).parents[1] / "src/coach/modules/gym/programs/sample.yaml"
NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)  # Tuesday 19:00 in Brisbane
GYM = Registry([GymModule()])


async def seeded(pool: Pool, athlete: Athlete) -> UUID:
    async with pool.connection() as conn:
        return await seed_program(
            conn,
            athlete,
            load_program(SAMPLE, library_index()),
            library_index(),
            source_file="sample.yaml",
        )


async def complete(pool: Pool, athlete: Athlete, position: int, started_at: datetime) -> None:
    async with pool.connection() as conn:
        session_id = await create_session(conn, athlete, discipline="gym", started_at=started_at)
        await conn.execute(
            "update program_sessions ps set completed_session_id = %s from programs p "
            "where ps.program_id = p.id and p.athlete_id = %s and p.active and ps.position = %s",
            (session_id, athlete.id, position),
        )


def ctx(athlete: Athlete, pool: Pool) -> CoachContext:
    return CoachContext(athlete=athlete, pool=pool, registry=GYM, now=lambda: NOW)


async def call_tool(athlete: Athlete, pool: Pool, name: str, args: dict[str, object]) -> str:
    model = scripted(
        AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "g1"}]), "ok"
    )
    out = await build_graph(model, GYM).ainvoke(
        {"messages": [HumanMessage("gym")]}, context=ctx(athlete, pool)
    )
    return next(m.text for m in out["messages"] if isinstance(m, ToolMessage))


async def test_get_program_shows_the_next_session_in_full(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)

    result = json.loads(await call_tool(athlete, pool, "get_program", {}))

    assert result["program"] == "Sample dumbbell program"
    assert result["progress"] == {"done": 0, "skipped": 0, "total": 4}
    assert result["this_week"] == {"done": 0, "target": 2}
    next_session = result["next_session"]
    assert next_session["label"] == "Week 1 Treino A"
    assert next_session["exercises"][2] == {
        "block": "main",
        "exercise": "Agachamento goblet",
        "sets": 3,
        "reps": "10",
        "rest_s": 90,
        "tempo": "3.0.1.0",
        "notes": None,
    }


async def test_progress_and_this_week_follow_completed_sessions(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)
    await complete(pool, athlete, 1, datetime(2026, 10, 5, 22, 0, tzinfo=UTC))  # Tue local

    result = json.loads(await call_tool(athlete, pool, "get_program", {}))

    assert result["progress"]["done"] == 1
    assert result["this_week"]["done"] == 1
    assert result["next_session"]["label"] == "Week 1 Treino B"


async def test_without_a_program_get_program_says_so(pool: Pool, athlete: Athlete) -> None:
    result = json.loads(await call_tool(athlete, pool, "get_program", {}))

    assert result["program"] is None


async def test_context_is_one_line(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)

    async with pool.connection() as conn:
        line = await GymModule().context(conn, athlete)

    assert line == (
        "Sample dumbbell program: 0/4 sessions done, 0/2 this week, next is Week 1 Treino A."
    )


def test_prompt_teaches_tempo_and_lists_the_library() -> None:
    athlete = Athlete(id=UUID(int=1), name="J", timezone="Australia/Brisbane", telegram_chat_id=1)

    prompt = GymModule().prompt(athlete)

    assert "4.0.X.0" in prompt
    assert "Agachamento goblet (goblet squat, goblet)" in prompt
