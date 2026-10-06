"""Runtime context passed to every graph node and tool, never chosen by the model."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from coach.core.db import Pool
from coach.core.models import Athlete, ReplyButton
from coach.core.registry import Registry


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CoachContext:
    """Who the turn is for and the dependencies the tools need."""

    athlete: Athlete
    pool: Pool
    registry: Registry
    now: Callable[[], datetime] = field(default=_utcnow)
    # Tools append; the handler sends them under the reply. Mutable on purpose.
    reply_buttons: list[ReplyButton] = field(default_factory=list)
