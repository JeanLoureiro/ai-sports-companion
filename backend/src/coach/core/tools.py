"""Core tools, bound to the agent whatever modules are enabled."""

import json
from datetime import timedelta
from typing import Annotated, Literal

from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import ToolRuntime
from pydantic import Field

from coach.core.context import CoachContext
from coach.core.repo import recent_sessions, sessions_per_discipline, weekly_load


@tool
async def query_history(
    kind: Literal["recent_sessions", "weekly_load", "per_discipline"],
    runtime: ToolRuntime[CoachContext],
    days: Annotated[int, Field(ge=1, le=365)] = 14,
) -> str:
    """Query the athlete's training history across every discipline.

    kind: recent_sessions lists sessions newest first; weekly_load totals sessions,
    minutes and load (minutes x RPE) per week in the athlete's time zone;
    per_discipline counts sessions and minutes per discipline.
    days: how many days back to look.
    """
    ctx = runtime.context
    since = ctx.now() - timedelta(days=days)
    async with ctx.pool.connection() as conn:
        match kind:
            case "recent_sessions":
                rows = await recent_sessions(conn, ctx.athlete, since=since)
            case "weekly_load":
                rows = await weekly_load(conn, ctx.athlete, since=since)
            case "per_discipline":
                rows = await sessions_per_discipline(conn, ctx.athlete, since=since)
    return json.dumps(rows, default=str)


CORE_TOOLS: list[BaseTool] = [query_history]
