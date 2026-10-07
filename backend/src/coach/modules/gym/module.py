"""The gym discipline module."""

from datetime import UTC, datetime
from pathlib import Path

from langchain_core.tools import BaseTool

from coach.core.db import Connection
from coach.core.models import Athlete
from coach.core.registry import ScheduledJob
from coach.modules.gym.library import library_index
from coach.modules.gym.tools import get_program, log_gym_session, program_summary

HERE = Path(__file__).parent
PROMPT = (HERE / "prompt.md").read_text(encoding="utf-8").strip()


class GymModule:
    """Program, next session, and logging against it."""

    name = "gym"
    migrations = HERE / "migrations"

    def tools(self) -> list[BaseTool]:
        return [get_program, log_gym_session]

    def prompt(self, athlete: Athlete) -> str:
        lines = [
            f"- {e.name} ({', '.join(e.aliases)})" if e.aliases else f"- {e.name}"
            for e in library_index()
        ]
        return f"{PROMPT}\n\nExercise library:\n" + "\n".join(lines)

    async def context(self, conn: Connection, athlete: Athlete) -> str:
        summary = await program_summary(conn, athlete, datetime.now(UTC))
        if summary is None:
            return ""
        progress, week = summary["progress"], summary["this_week"]
        upcoming = summary["next_session"]
        next_part = f"next is {upcoming['label']}" if upcoming else "the program is complete"
        return (
            f"{summary['program']}: {progress['done']}/{progress['total']} sessions done, "
            f"{week['done']}/{week['target']} this week, {next_part}."
        )

    def canonical(self, name: str) -> str | None:
        """The library name for an exercise name or alias, for eval scoring."""
        exercise = library_index().resolve(name)
        return exercise.name if exercise else None

    def jobs(self) -> list[ScheduledJob]:
        return []

    def evals(self) -> list[Path]:
        return [HERE / "evals" / "extraction.yaml"]
