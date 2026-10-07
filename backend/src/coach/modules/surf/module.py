"""The surf discipline module."""

from pathlib import Path

from langchain_core.tools import BaseTool

from coach.core.db import Connection
from coach.core.models import Athlete
from coach.core.registry import ScheduledJob

HERE = Path(__file__).parent


class SurfModule:
    """Spots, logging, history and forecasts rated per spot."""

    name = "surf"
    migrations = HERE / "migrations"

    def tools(self) -> list[BaseTool]:
        return []

    def prompt(self, athlete: Athlete) -> str:
        return ""

    async def context(self, conn: Connection, athlete: Athlete) -> str:
        return ""

    def canonical(self, name: str) -> str | None:
        """Spot names are resolved per athlete in the database, so evals compare them as said."""
        return None

    def jobs(self) -> list[ScheduledJob]:
        return []

    def evals(self) -> list[Path]:
        return []
