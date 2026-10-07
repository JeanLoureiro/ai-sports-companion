"""Surf tools bound to the agent."""

import json
from datetime import datetime, timedelta
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import interrupt
from pydantic import Field

from coach.core.context import CoachContext
from coach.core.models import Location, ReplyButton
from coach.core.repo import create_session
from coach.modules.surf.forecast import (
    ESTIMATE_NOTE,
    ForecastError,
    Spot,
    fetch_hours,
    tide_events,
    windows,
)
from coach.modules.surf.repo import insert_details, surf_sessions
from coach.modules.surf.spots import add_alias, create_spot, list_spots, resolve_spot


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


@tool
async def log_surf_session(
    runtime: ToolRuntime[CoachContext],
    spot: Annotated[str, Field(description="Spot as the athlete said it, e.g. 'Burleigh'")],
    started_at: Annotated[
        datetime | None, Field(description="Local date and time; omit for now")
    ] = None,
    duration_min: Annotated[int | None, Field(ge=1, le=600)] = None,
    rpe: Annotated[int | None, Field(ge=1, le=10)] = None,
    wave_height_min_ft: Annotated[float | None, Field(ge=0, le=60)] = None,
    wave_height_max_ft: Annotated[float | None, Field(ge=0, le=60)] = None,
    wind: Annotated[str | None, Field(description="As said: offshore, onshore, light...")] = None,
    tide: Annotated[str | None, Field(description="As said: low, mid, high, pushing...")] = None,
    waves_caught: Annotated[int | None, Field(ge=0, le=500)] = None,
    board: Annotated[str | None, Field(description="As said, e.g. 6'0 shortboard")] = None,
    notes: Annotated[str | None, Field(description="Anything else, in their words")] = None,
) -> str:
    """Log one surf session. Fill only what the athlete said; never guess heights or waves.
    For an unknown spot the athlete is asked for a location pin first."""
    ctx = runtime.context
    async with ctx.pool.connection() as conn:
        found = await resolve_spot(conn, ctx.athlete, spot)
        names = [s["name"] for s in await list_spots(conn, ctx.athlete)]
    if found is None:
        # The tool runs again from the top when the athlete answers: nothing is written before.
        answer = interrupt(
            {
                "question": (
                    f"I don't know {spot} yet. Send me a location pin for it, or tell me which "
                    f"of your spots it was: {', '.join(names) or 'none saved yet'}."
                )
            }
        )
        found = await _spot_from_answer(ctx, spot, answer)
    details = {
        "spot_id": found["id"] if found else None,
        "wave_height_min_ft": wave_height_min_ft,
        "wave_height_max_ft": wave_height_max_ft,
        "wind": wind,
        "tide": tide,
        "waves_caught": waves_caught,
        "board": board,
        "notes": notes,
    }
    place = found["name"] if found else spot
    async with ctx.pool.connection() as conn, conn.transaction():
        session_id = await create_session(
            conn,
            ctx.athlete,
            discipline="surf",
            started_at=ctx.local_to_utc(started_at),
            duration_min=duration_min,
            rpe=rpe,
            summary=f"Surf at {place}",
        )
        await insert_details(conn, session_id, details)
    ctx.reply_buttons.append(ReplyButton(text="Undo", data=f"undo:{session_id}"))
    saved = "" if found else " (not a saved spot: logged without one)"
    logged = {k: v for k, v in details.items() if v is not None and k != "spot_id"}
    return f"Logged surf at {place}{saved}. Details: {_dump(logged)}"


async def _spot_from_answer(
    ctx: CoachContext, said: str, answer: dict[str, Any]
) -> dict[str, Any] | None:
    """A pin creates the spot; naming a saved spot reuses it and learns the new name."""
    location = answer.get("location")
    async with ctx.pool.connection() as conn:
        if location:
            return await create_spot(
                conn,
                ctx.athlete,
                said.strip().title(),
                Location(location["latitude"], location["longitude"]),
            )
        named = await resolve_spot(conn, ctx.athlete, answer.get("text") or "")
        if named is not None:
            await add_alias(conn, named["id"], said.strip())
        return named
