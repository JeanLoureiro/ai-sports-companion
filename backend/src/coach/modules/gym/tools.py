"""Gym tools bound to the agent."""

import json
from datetime import datetime
from typing import Any

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from coach.core.context import CoachContext
from coach.core.db import Connection
from coach.core.models import Athlete
from coach.core.tools import history_window
from coach.modules.gym.repo import active_program, done_since, next_pending, prescriptions, progress


async def program_summary(
    conn: Connection, athlete: Athlete, now: datetime
) -> dict[str, Any] | None:
    """Progress, this week against the target, and the next session in full."""
    program = await active_program(conn, athlete)
    if program is None:
        return None
    week_start, _ = history_window("this_week", 7, now, athlete.timezone)
    upcoming = await next_pending(conn, program["id"])
    next_session = None
    if upcoming is not None:
        next_session = {
            "position": upcoming["position"],
            "label": upcoming["label"],
            "planned_date": upcoming["planned_date"],
            "exercises": await prescriptions(conn, upcoming["id"]),
        }
    return {
        "program": program["name"],
        "progress": await progress(conn, program["id"]),
        "this_week": {
            "done": await done_since(conn, program["id"], week_start),
            "target": program["sessions_per_week_target"],
        },
        "next_session": next_session,
    }


@tool
async def get_program(runtime: ToolRuntime[CoachContext]) -> str:
    """The athlete's gym program: progress, sessions done this week against the target, and the
    next pending session with every exercise as prescribed (sets, reps, rest in seconds, tempo
    as cadência such as 4.0.X.0, and notes). Use it for "what's my next session?"."""
    ctx = runtime.context
    async with ctx.pool.connection() as conn:
        summary = await program_summary(conn, ctx.athlete, ctx.now())
    if summary is None:
        summary = {"program": None, "message": "No active gym program has been seeded."}
    return json.dumps(summary, default=str, ensure_ascii=False)
