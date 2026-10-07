"""Runtime context passed to every graph node and tool, never chosen by the model."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx

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
    # For tools that call external APIs (forecasts); tests pass a mock transport.
    http: httpx.AsyncClient | None = None
    # Tools append; the handler sends them under the reply. Mutable on purpose.
    reply_buttons: list[ReplyButton] = field(default_factory=list)

    def local_to_utc(self, value: datetime | None) -> datetime:
        """None is now; a time without a zone is the athlete's local time."""
        if value is None:
            return self.now()
        if value.tzinfo is None:
            return value.replace(tzinfo=ZoneInfo(self.athlete.timezone)).astimezone(UTC)
        return value
