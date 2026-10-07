"""Surf tools bound to the agent."""

import json
from datetime import timedelta
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import Field

from coach.core.context import CoachContext
from coach.modules.surf.forecast import (
    ESTIMATE_NOTE,
    ForecastError,
    Spot,
    fetch_hours,
    tide_events,
    windows,
)
from coach.modules.surf.repo import surf_sessions
from coach.modules.surf.spots import list_spots, resolve_spot


def _dump(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


@tool
async def get_surf_forecast(
    runtime: ToolRuntime[CoachContext],
    spot: Annotated[
        str | None, Field(description="Spot as the athlete said it; omit for all favourites")
    ] = None,
    days: Annotated[int, Field(ge=1, le=3)] = 2,
) -> str:
    """Swell, wind and tide for the next days at one spot or every favourite, with each
    morning, midday and afternoon rated 0 to 5 for that spot. Estimates, not a surf report."""
    ctx = runtime.context
    if ctx.http is None:
        raise RuntimeError("no HTTP client in the context")
    async with ctx.pool.connection() as conn:
        if spot:
            found = await resolve_spot(conn, ctx.athlete, spot)
            if found is None:
                known = [s["name"] for s in await list_spots(conn, ctx.athlete)]
                return _dump({"error": f"unknown spot {spot!r}", "known_spots": known})
            rows = [found]
        else:
            rows = [s for s in await list_spots(conn, ctx.athlete) if s["favourite"]]
    report = []
    for row in rows:
        target = Spot.from_row(row)
        try:
            hours = await fetch_hours(ctx.http, target, days=days, timezone=ctx.athlete.timezone)
        except ForecastError as err:
            return _dump({"error": str(err)})
        report.append(
            {"name": target.name, "windows": windows(target, hours), "tides": tide_events(hours)}
        )
    return _dump({"note": ESTIMATE_NOTE, "spots": report})


@tool
async def surf_history(
    runtime: ToolRuntime[CoachContext],
    spot: Annotated[str | None, Field(description="Spot as said; omit for every spot")] = None,
    days: Annotated[int, Field(ge=1, le=365)] = 90,
) -> str:
    """Surf sessions per spot over the last days: count, last session, average waves caught,
    and the best session (most waves) with its conditions."""
    ctx = runtime.context
    async with ctx.pool.connection() as conn:
        spot_id = None
        if spot:
            found = await resolve_spot(conn, ctx.athlete, spot)
            if found is None:
                return _dump({"error": f"unknown spot {spot!r}"})
            spot_id = found["id"]
        sessions = await surf_sessions(
            conn, ctx.athlete, since=ctx.now() - timedelta(days=days), spot_id=spot_id
        )
    by_spot: dict[str, list[dict[str, Any]]] = {}
    for session in sessions:
        by_spot.setdefault(session["spot"] or "unknown spot", []).append(session)
    report = []
    for name, rows in by_spot.items():
        waves = [r["waves_caught"] for r in rows if r["waves_caught"] is not None]
        best = max(rows, key=lambda r: r["waves_caught"] or 0)
        report.append(
            {
                "spot": name,
                "sessions": len(rows),
                "last": rows[0]["started_at"],
                "avg_waves": round(sum(waves) / len(waves), 1) if waves else None,
                "best": {
                    k: best[k]
                    for k in (
                        "started_at",
                        "wave_height_min_ft",
                        "wave_height_max_ft",
                        "wind",
                        "tide",
                        "waves_caught",
                    )
                },
            }
        )
    return _dump({"spots": report})
