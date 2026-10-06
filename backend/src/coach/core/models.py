"""Plain data objects passed between the core layers."""

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

type Trigger = Literal["message", "schedule"]


@dataclass(frozen=True, slots=True)
class Athlete:
    """The person being coached."""

    id: UUID
    name: str
    timezone: str
    telegram_chat_id: int | None


@dataclass(frozen=True, slots=True)
class AgentRun:
    """One agent turn as stored in ``agent_runs``."""

    athlete_id: UUID
    trigger: Trigger
    input: str
    output: str
    model: str
    latency_ms: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
