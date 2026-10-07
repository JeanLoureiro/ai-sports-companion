"""Discipline modules and the registry that wires them into the core."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from langchain_core.tools import BaseTool

from coach.core.migrations import CORE_MIGRATIONS, MigrationDir
from coach.core.models import Athlete

if TYPE_CHECKING:
    from coach.core.context import CoachContext
    from coach.core.db import Connection


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    """A proactive job; ``is_due`` receives the athlete's local time (used from week 5)."""

    name: str
    is_due: Callable[[Athlete, datetime], bool]
    run: Callable[[CoachContext], Awaitable[None]]


class DisciplineModule(Protocol):
    """Everything a sport contributes. Modules never import each other."""

    name: str
    migrations: Path

    def tools(self) -> list[BaseTool]: ...

    def prompt(self, athlete: Athlete) -> str: ...

    async def context(self, conn: Connection, athlete: Athlete) -> str: ...

    def jobs(self) -> list[ScheduledJob]: ...

    def evals(self) -> list[Path]: ...


class Registry:
    """The enabled modules, validated once, queried by the graph, CLI and job tick."""

    def __init__(self, modules: Sequence[DisciplineModule]) -> None:
        names = [m.name for m in modules]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate module names: {names}")
        if "core" in names:
            raise ValueError('"core" is reserved for core tools and migrations')
        self._modules = tuple(modules)
        self._tool_owner: dict[str, str] = {}
        for module in self._modules:
            for module_tool in module.tools():
                if module_tool.name in self._tool_owner:
                    raise ValueError(f"tool {module_tool.name!r} is registered twice")
                self._tool_owner[module_tool.name] = module.name

    @property
    def modules(self) -> tuple[DisciplineModule, ...]:
        """The enabled modules, in migration order."""
        return self._modules

    def tools(self) -> list[BaseTool]:
        """Every module tool, to bind next to the core tools."""
        return [t for m in self._modules for t in m.tools()]

    def tool_owner(self, tool_name: str) -> str:
        """The module that owns a tool, or ``"core"``."""
        return self._tool_owner.get(tool_name, "core")

    def prompt(self, athlete: Athlete) -> str:
        """The modules' system prompt fragments, joined."""
        fragments = (m.prompt(athlete).strip() for m in self._modules)
        return "\n\n".join(f for f in fragments if f)

    async def context(self, conn: Connection, athlete: Athlete) -> str:
        """One ``module: summary`` line per module with something to say."""
        lines: list[str] = []
        for module in self._modules:
            text = (await module.context(conn, athlete)).strip()
            if text:
                lines.append(f"{module.name}: {text}")
        return "\n".join(lines)

    def migration_dirs(self) -> list[MigrationDir]:
        """Core migrations first, then each module's."""
        return [("core", CORE_MIGRATIONS), *((m.name, m.migrations) for m in self._modules)]


def default_registry() -> Registry:
    """The enabled discipline modules, in migration order. Phase 2 adds BJJ."""
    from coach.modules.gym.module import GymModule  # local: modules import from the core
    from coach.modules.surf.module import SurfModule

    return Registry([GymModule(), SurfModule()])
