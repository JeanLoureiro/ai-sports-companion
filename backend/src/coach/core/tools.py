"""Core tools, bound to the agent whatever modules are enabled."""

import json
from datetime import datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import ToolRuntime
from pydantic import Field

from coach.core.context import CoachContext
from coach.core.repo import recent_sessions, sessions_per_discipline, weekly_load

type Period = Literal["this_week", "last_week", "last_n_days"]


def history_window(
    period: Period, days: int, now: datetime, timezone: str
) -> tuple[datetime, datetime]:
    """The ``[since, until)`` window for a period, with weeks starting Monday 00:00 local time."""
    if period == "last_n_days":
        return now - timedelta(days=days), now
    local_now = now.astimezone(ZoneInfo(timezone))
    monday = (local_now - timedelta(days=local_now.weekday())).date()
    week_start = datetime.combine(monday, datetime.min.time(), tzinfo=ZoneInfo(timezone))
    if period == "this_week":
        return week_start, now
    previous = datetime.combine(
        monday - timedelta(days=7), datetime.min.time(), tzinfo=ZoneInfo(timezone)
    )
    return previous, week_start


@tool
async def query_history(
    kind: Literal["recent_sessions", "weekly_load", "per_discipline"],
    runtime: ToolRuntime[CoachContext],
    period: Period = "last_n_days",
    days: Annotated[int, Field(ge=1, le=365)] = 14,
) -> str:
    """Query the athlete's training history across every discipline.

    kind: recent_sessions lists sessions newest first, with local start time and weekday;
    weekly_load totals sessions, minutes and load (minutes x RPE) per local week;
    per_discipline counts sessions and minutes per discipline.
    period: this_week and last_week are calendar weeks (Monday to Sunday) in the athlete's
    time zone; last_n_days is a rolling window of ``days`` days ending now.
    days: only used with last_n_days.
    """
    ctx = runtime.context
    since, until = history_window(period, days, ctx.now(), ctx.athlete.timezone)
    async with ctx.pool.connection() as conn:
        match kind:
            case "recent_sessions":
                rows = await recent_sessions(conn, ctx.athlete, since=since, until=until)
            case "weekly_load":
                rows = await weekly_load(conn, ctx.athlete, since=since, until=until)
            case "per_discipline":
                rows = await sessions_per_discipline(conn, ctx.athlete, since=since, until=until)
    return json.dumps(rows, default=str)


CORE_TOOLS: list[BaseTool] = [query_history]
