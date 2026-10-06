import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from coach.core.context import CoachContext
from coach.core.db import Pool
from coach.core.graph import build_graph
from coach.core.models import Athlete
from coach.core.registry import Registry
from coach.core.repo import create_session, undo_session
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


async def gym_rows(pool: Pool, athlete: Athlete) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "select s.id, s.started_at, s.rpe, s.summary, ps.label, gd.lifts "
            "from sessions s join gym_details gd on gd.session_id = s.id "
            "left join program_sessions ps on ps.id = gd.program_session_id "
            "where s.athlete_id = %s order by s.created_at",
            (athlete.id,),
        )
        return await cur.fetchall()


async def test_logs_the_next_session_with_the_loads_mentioned(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)
    turn = ctx(athlete, pool)
    model = scripted(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "log_gym_session",
                    "id": "l1",
                    "args": {
                        "day": None,
                        "rpe": 7,
                        "lifts": [{"exercise": "goblet squat", "load_kg": 22}],
                    },
                }
            ],
        ),
        "Logged.",
    )

    await build_graph(model, GYM).ainvoke({"messages": [HumanMessage("did A")]}, context=turn)

    [row] = await gym_rows(pool, athlete)
    assert row["label"] == "Week 1 Treino A"
    assert row["rpe"] == 7
    lifts = {lift["exercise"]: lift for lift in row["lifts"]}
    assert lifts["Agachamento goblet"]["load_kg"] == 22
    assert lifts["Agachamento goblet"]["done"] is True
    assert lifts["Remada curvada"]["done"] is True  # not mentioned: done as prescribed
    assert "Volta ao mundo" not in lifts  # prep block is assumed, not stored
    assert turn.reply_buttons[0].data == f"undo:{row['id']}"


async def test_a_named_day_picks_the_first_pending_session_with_that_label(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)

    await call_tool(athlete, pool, "log_gym_session", {"day": "Treino B"})

    [row] = await gym_rows(pool, athlete)
    assert row["label"] == "Week 1 Treino B"


async def test_a_day_with_nothing_pending_is_logged_as_an_extra_session(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)
    await complete(pool, athlete, 2, NOW)
    await complete(pool, athlete, 4, NOW)

    result = await call_tool(athlete, pool, "log_gym_session", {"day": "B"})

    assert "extra" in result.lower()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "select count(*)::int as n from program_sessions ps join programs p "
            "on p.id = ps.program_id where p.athlete_id = %s "
            "and ps.completed_session_id is not null",
            (athlete.id,),
        )
        assert await cur.fetchone() == {"n": 2}


async def test_swaps_skips_and_unknown_exercises_are_kept(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)

    await call_tool(
        athlete,
        pool,
        "log_gym_session",
        {
            "day": None,
            "lifts": [
                {"exercise": "Remada curvada", "swapped_to": "push ups"},
                {"exercise": "goblet", "skipped": True},
                {"exercise": "bulgarian bag spin", "sets": 2},
            ],
        },
    )

    [row] = await gym_rows(pool, athlete)
    lifts = {lift["exercise"]: lift for lift in row["lifts"]}
    assert lifts["Remada curvada"]["swapped_to"] == "push ups"
    assert lifts["Agachamento goblet"]["done"] is False
    assert lifts["bulgarian bag spin"] == {
        "exercise": "bulgarian bag spin",
        "extra": True,
        "known": False,
        "done": True,
        "sets": 2,
    }


async def test_a_time_without_a_zone_is_the_athletes_local_time(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)

    await call_tool(
        athlete, pool, "log_gym_session", {"day": None, "started_at": "2026-10-06T07:00:00"}
    )

    [row] = await gym_rows(pool, athlete)
    assert row["started_at"] == datetime(2026, 10, 5, 21, 0, tzinfo=UTC)


async def test_undo_frees_the_program_slot(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)
    await call_tool(athlete, pool, "log_gym_session", {"day": None})
    [row] = await gym_rows(pool, athlete)

    async with pool.connection() as conn:
        assert await undo_session(conn, athlete, row["id"]) is not None
    result = json.loads(await call_tool(athlete, pool, "get_program", {}))

    assert result["next_session"]["label"] == "Week 1 Treino A"
    assert result["progress"]["done"] == 0


async def test_a_field_the_tool_does_not_know_is_an_error_not_a_silent_drop(
    pool: Pool, athlete: Athlete
) -> None:
    # The model once nested rpe inside a lift; dropping it silently loses the athlete's RPE.
    await seeded(pool, athlete)

    model = scripted(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "log_gym_session",
                    "id": "x1",
                    "args": {
                        "day": None,
                        "lifts": [{"exercise": "goblet", "load_kg": 22, "rpe": 7}],
                    },
                }
            ],
        ),
        "ok",
    )
    out = await build_graph(model, GYM).ainvoke(
        {"messages": [HumanMessage("gym")]}, context=ctx(athlete, pool)
    )

    tool_message = next(m for m in out["messages"] if isinstance(m, ToolMessage))
    assert tool_message.status == "error"
    assert "rpe" in tool_message.text
    assert await gym_rows(pool, athlete) == []


def test_the_tool_tells_the_model_to_pass_the_named_day() -> None:
    from coach.modules.gym.tools import log_gym_session

    schema = log_gym_session.args
    assert "always" in schema["day"]["description"].lower()
    assert "Treino B" in GymModule().prompt(Athlete(UUID(int=1), "J", "Australia/Brisbane", 1))


def test_day_is_required_so_the_model_decides_on_purpose() -> None:
    from langchain_core.utils.function_calling import convert_to_openai_tool

    from coach.modules.gym.tools import log_gym_session

    parameters = convert_to_openai_tool(log_gym_session)["function"]["parameters"]
    assert "day" in parameters["required"]


async def test_a_day_the_program_does_not_have_is_an_error(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)

    result = await call_tool(athlete, pool, "log_gym_session", {"day": "Wednesday"})

    assert "A, B" in result
    assert await gym_rows(pool, athlete) == []


@pytest.mark.parametrize(
    ("said", "planned_day", "expected"),
    [
        ("rows", "A", "Remada curvada"),
        ("remada", "A", "Remada curvada"),
        ("rows", "B", "Serrote"),
        ("sumo", "B", "Agachamento terra sumo"),
    ],
)
async def test_short_names_resolve_within_the_session_being_logged(
    pool: Pool, athlete: Athlete, said: str, planned_day: str, expected: str
) -> None:
    await seeded(pool, athlete)

    await call_tool(
        athlete,
        pool,
        "log_gym_session",
        {"day": planned_day, "lifts": [{"exercise": said, "load_kg": 20}]},
    )

    [row] = await gym_rows(pool, athlete)
    lifts = {lift["exercise"]: lift for lift in row["lifts"]}
    assert lifts[expected]["load_kg"] == 20
    assert not any(lift.get("extra") for lift in row["lifts"])


async def test_notes_are_kept_with_the_session(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)

    await call_tool(athlete, pool, "log_gym_session", {"day": None, "notes": "knee was cranky"})

    async with pool.connection() as conn:
        cur = await conn.execute(
            "select gd.notes from gym_details gd join sessions s on s.id = gd.session_id "
            "where s.athlete_id = %s",
            (athlete.id,),
        )
        assert await cur.fetchone() == {"notes": "knee was cranky"}


def test_prompt_asks_for_the_athletes_own_words() -> None:
    prompt = GymModule().prompt(Athlete(UUID(int=1), "J", "Australia/Brisbane", 1))

    assert "as the athlete said" in prompt.lower()
    assert "Use the Portuguese name in tool calls" not in prompt
