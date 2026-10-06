"""The exercise library and name matching across Portuguese names and English aliases."""

import re
import unicodedata
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

LIBRARY_PATH = Path(__file__).parent / "exercises.yaml"

type Pattern = Literal[
    "push",
    "pull",
    "hinge",
    "squat",
    "lunge",
    "carry",
    "core",
    "mobility",
    "stability",
    "plyometric",
]


def normalize(text: str) -> str:
    """Casefold, strip accents, turn punctuation into single spaces (keeps '/' for 90/90)."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9/]+", " ", plain).split())


class ExerciseDef(BaseModel):
    """One exercise: the coach's name, aliases, and what it trains and loads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    aliases: tuple[str, ...] = ()
    pattern: Pattern
    equipment: tuple[str, ...] = ()
    load_areas: tuple[str, ...] = ()


def load_library(path: Path) -> list[ExerciseDef]:
    """Read ``exercises:`` from a YAML file."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [ExerciseDef.model_validate(item) for item in data["exercises"]]


class ExerciseIndex:
    """Resolves any name or alias, in any case and with or without accents."""

    def __init__(self, exercises: list[ExerciseDef]) -> None:
        self._exercises = list(exercises)
        self._by_key: dict[str, ExerciseDef] = {}
        for exercise in self._exercises:
            for key in (exercise.name, *exercise.aliases):
                normal = normalize(key)
                existing = self._by_key.get(normal)
                if existing is not None and existing != exercise:
                    raise ValueError(f"{key!r} names both {existing.name!r} and {exercise.name!r}")
                self._by_key[normal] = exercise

    def resolve(self, name: str) -> ExerciseDef | None:
        """The exercise this name refers to, or None."""
        return self._by_key.get(normalize(name))

    def __iter__(self) -> Iterator[ExerciseDef]:
        return iter(self._exercises)


def canonical_name(text: str) -> str:
    """The normalized library name when the text names a known exercise, else the text."""
    exercise = library_index().resolve(text)
    return normalize(exercise.name if exercise else text)


@cache
def library_index() -> ExerciseIndex:
    """The shipped library, loaded once."""
    return ExerciseIndex(load_library(LIBRARY_PATH))
