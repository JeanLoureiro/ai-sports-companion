import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from coach.core.context import CoachContext
from coach.core.db import Pool
from coach.core.graph import build_graph
from coach.core.models import Athlete
from coach.core.registry import Registry
from coach.core.repo import create_session
from coach.modules.surf.forecast import MARINE_URL
from coach.modules.surf.module import SurfModule
from coach.modules.surf.seed import seed_spots
from coach.modules.surf.spots import SPOTS_PATH, load_spots, resolve_spot
from tests.fakes import scripted

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 7, 21, 0, tzinfo=UTC)  # Thursday 07:00 in Brisbane
SURF = Registry([SurfModule()])


def forecast_http(status: int = 200) -> httpx.AsyncClient:
    times = [f"2026-10-08T{h:02d}:00" for h in range(24)]
    marine = {
        "hourly": {
            "time": times,
            "swell_wave_height": [1.1] * 24,
            "swell_wave_period": [10.0] * 24,
            "swell_wave_direction": [110.0] * 24,
            "sea_level_height_msl": [((h - 6) % 12) / 10 for h in range(24)],
        }
    }
    weather = {
        "hourly": {
            "time": times,
            "wind_speed_10m": [5.0] * 8 + [15.0] * 16,
            "wind_direction_10m": [250.0] * 8 + [60.0] * 16,
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = marine if str(request.url).startswith(MARINE_URL) else weather
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def seeded(pool: Pool, athlete: Athlete) -> None:
    async with pool.connection() as conn:
        await seed_spots(conn, athlete, load_spots(SPOTS_PATH))


def ctx(athlete: Athlete, pool: Pool, http: httpx.AsyncClient | None = None) -> CoachContext:
    return CoachContext(
        athlete=athlete, pool=pool, registry=SURF, now=lambda: NOW, http=http or forecast_http()
    )


async def call_tool(context: CoachContext, name: str, args: dict[str, Any]) -> str:
    model = scripted(
        AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "s1"}]), "ok"
    )
    out = await build_graph(model, SURF).ainvoke(
        {"messages": [HumanMessage("surf")]}, context=context
    )
    return next(m.text for m in out["messages"] if isinstance(m, ToolMessage))


async def test_forecast_for_one_spot_rates_the_morning_best(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)

    result = json.loads(
        await call_tool(ctx(athlete, pool), "get_surf_forecast", {"spot": "snapper", "days": 1})
    )

    [snapper] = result["spots"]
    assert snapper["name"] == "Snapper Rocks"
    morning = snapper["windows"][0]
    assert (morning["window"], morning["wind"], morning["rating"]) == ("morning", "offshore", 5)
    assert snapper["tides"]
    assert "regional" in result["note"]


async def test_forecast_without_a_spot_covers_every_favourite(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)

    result = json.loads(await call_tool(ctx(athlete, pool), "get_surf_forecast", {"days": 1}))

    assert {s["name"] for s in result["spots"]} == {
        "Burleigh Heads",
        "Snapper Rocks",
        "Currumbin Alley",
        "Duranbah",
    }


async def test_forecast_for_an_unknown_spot_lists_the_known_ones(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)

    result = json.loads(
        await call_tool(ctx(athlete, pool), "get_surf_forecast", {"spot": "pipeline"})
    )

    assert "unknown spot" in result["error"]
    assert "Duranbah" in result["known_spots"]


async def test_forecast_outage_is_reported_not_raised(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)

    result = json.loads(
        await call_tool(
            ctx(athlete, pool, forecast_http(502)), "get_surf_forecast", {"spot": "burleigh"}
        )
    )

    assert "unavailable" in result["error"]


async def test_history_groups_sessions_by_spot(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)
    async with pool.connection() as conn:
        burleigh = await resolve_spot(conn, athlete, "burleigh")
        assert burleigh is not None
        for days_ago, waves in ((3, 12), (10, 6)):
            session_id = await create_session(
                conn, athlete, discipline="surf", started_at=NOW - timedelta(days=days_ago)
            )
            await conn.execute(
                "insert into surf_details (session_id, spot_id, waves_caught, "
                "wave_height_min_ft, wave_height_max_ft) values (%s, %s, %s, 3, 4)",
                (session_id, burleigh["id"], waves),
            )

    result = json.loads(await call_tool(ctx(athlete, pool), "surf_history", {}))

    [spot] = result["spots"]
    assert (spot["spot"], spot["sessions"], spot["avg_waves"]) == ("Burleigh Heads", 2, 9.0)
    assert spot["best"]["waves_caught"] == 12
