from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from coach.core.context import CoachContext
from coach.core.db import Pool
from coach.core.graph import build_graph
from coach.core.models import Athlete, Location
from coach.core.registry import Registry
from coach.core.turn import run_turn
from coach.modules.gym.library import library_index
from coach.modules.gym.module import GymModule
from coach.modules.gym.program import load_program
from coach.modules.gym.seed import seed_program
from coach.modules.surf.module import SurfModule
from coach.modules.surf.seed import seed_spots
from coach.modules.surf.spots import SPOTS_PATH, load_spots
from tests.fakes import scripted

pytestmark = pytest.mark.anyio

SAMPLE = Path(__file__).parents[1] / "src/coach/modules/gym/programs/sample.yaml"
BOTH = Registry([GymModule(), SurfModule()])


async def test_a_sibling_log_is_not_repeated_when_a_question_is_answered(
    pool: Pool, athlete: Athlete
) -> None:
    async with pool.connection() as conn:
        await seed_spots(conn, athlete, load_spots(SPOTS_PATH))
        await seed_program(
            conn,
            athlete,
            load_program(SAMPLE, library_index()),
            library_index(),
            source_file="sample.yaml",
        )
    model = scripted(
        AIMessage(
            content="",
            tool_calls=[
                {"name": "log_gym_session", "args": {"day": None}, "id": "g1"},
                {"name": "log_surf_session", "args": {"spot": "Kirra"}, "id": "s1"},
            ],
        ),
        "Logged both.",
    )
    graph = build_graph(model, BOTH, InMemorySaver())
    ctx = CoachContext(athlete=athlete, pool=pool, registry=BOTH)

    await run_turn(graph, ctx, "surfed kirra then did gym", model_name="m")
    done = await run_turn(
        graph, ctx, "(shared a location)", model_name="m", location=Location(-28.167, 153.531)
    )

    assert done.reply == "Logged both."
    async with pool.connection() as conn:
        cur = await conn.execute(
            "select discipline, count(*)::int as n from sessions where athlete_id = %s "
            "group by discipline order by discipline",
            (athlete.id,),
        )
        assert await cur.fetchall() == [
            {"discipline": "gym", "n": 1},
            {"discipline": "surf", "n": 1},
        ]
