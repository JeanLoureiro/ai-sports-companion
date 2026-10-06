"""The gym discipline module."""

from pathlib import Path

from langchain_core.tools import BaseTool

from coach.core.db import Connection
from coach.core.models import Athlete
from coach.core.registry import ScheduledJob

HERE = Path(__file__).parent


class GymModule:
    """Program, next session, and logging against it."""

    name = "gym"
    migrations = HERE / "migrations"

    def tools(self) -> list[BaseTool]:
        return []

    def prompt(self, athlete: Athlete) -> str:
        return ""

    async def context(self, conn: Connection, athlete: Athlete) -> str:
        return ""

    def jobs(self) -> list[ScheduledJob]:
        return []

    def evals(self) -> list[Path]:
        return []
