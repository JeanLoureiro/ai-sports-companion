"""The surf discipline module."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from langchain_core.tools import BaseTool

from coach.core.db import Connection
from coach.core.models import Athlete
from coach.core.registry import ScheduledJob
from coach.core.text import normalize
from coach.modules.surf.repo import surf_sessions
from coach.modules.surf.spots import SPOTS_PATH, load_spots, spot_keys
from coach.modules.surf.tools import get_surf_forecast, log_surf_session, surf_history

HERE = Path(__file__).parent
PROMPT = (HERE / "prompt.md").read_text(encoding="utf-8").strip()


class SurfModule:
    """Spots, logging, history and forecasts rated per spot."""

    name = "surf"
    migrations = HERE / "migrations"

    def tools(self) -> list[BaseTool]:
        return [log_surf_session, get_surf_forecast, surf_history]

    def prompt(self, athlete: Athlete) -> str:
        return PROMPT

    async def context(self, conn: Connection, athlete: Athlete) -> str:
        now = datetime.now(UTC)
        recent = await surf_sessions(conn, athlete, since=now - timedelta(days=14))
        if not recent:
            return ""
        last = recent[0]
        today = now.astimezone(ZoneInfo(athlete.timezone)).date()
        days_ago = (today - last["started_at"].date()).days
        when = (
            "today" if days_ago == 0 else "yesterday" if days_ago == 1 else f"{days_ago} days ago"
        )
        low, high = last["wave_height_min_ft"], last["wave_height_max_ft"]
        if low is not None and high is not None:
            size = f"{low:g}-{high:g} ft"
        elif high is not None:
            size = f"{high:g} ft"
        else:
            size = "size not logged"
        waves = f", {last['waves_caught']} waves" if last["waves_caught"] is not None else ""
        return (
            f"Last surf {when} at {last['spot'] or 'an unsaved spot'} ({size}{waves}); "
            f"{len(recent)} surfs in the last 14 days."
        )

    def canonical(self, name: str) -> str | None:
        """The shipped spot a name refers to, for eval scoring (athletes' own spots live in
        the database and are resolved by the tools)."""
        wanted = normalize(name)
        for spot in load_spots(SPOTS_PATH):
            row = {"name": spot.name, "aliases": spot.aliases}
            if wanted in spot_keys(row) or wanted.replace(" ", "") in spot_keys(row):
                return spot.name
        return None

    def jobs(self) -> list[ScheduledJob]:
        return []

    def evals(self) -> list[Path]:
        return [HERE / "evals" / "extraction.yaml"]
