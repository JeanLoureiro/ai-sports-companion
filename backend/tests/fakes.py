"""Test doubles shared across the suite."""

from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from coach.core.db import Connection
from coach.core.models import Athlete
from coach.core.registry import ScheduledJob


@tool
def fake_lookup(query: str) -> str:
    """Look something up in the fake sport."""
    return f"fake:{query}"


@dataclass
class FakeModule:
    """A discipline module with canned answers."""

    name: str = "fakesport"
    migrations: Path = Path("/nonexistent")
    module_tools: list[BaseTool] = field(default_factory=lambda: [fake_lookup])
    prompt_text: str = "FAKE PROMPT"
    context_text: str = "fake context line"

    def tools(self) -> list[BaseTool]:
        return list(self.module_tools)

    def prompt(self, athlete: Athlete) -> str:
        return self.prompt_text

    async def context(self, conn: Connection, athlete: Athlete) -> str:
        return self.context_text

    def jobs(self) -> list[ScheduledJob]:
        return []

    def evals(self) -> list[Path]:
        return []
