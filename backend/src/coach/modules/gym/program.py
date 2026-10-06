"""Program files: an ordered list of sessions, each a list of prescriptions."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from coach.modules.gym.library import ExerciseIndex


class Prescription(BaseModel):
    """One exercise as the coach wrote it for one session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exercise: str
    block: Literal["prep", "main"]
    sets: int = Field(ge=1)
    reps: str
    rest_s: int | None = Field(default=None, ge=0)
    tempo: str | None = None
    notes: str | None = None


class ProgramSession(BaseModel):
    """One session in the sequence (e.g. week 2, Treino B)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    week: int = Field(ge=1)
    day: str
    exercises: tuple[Prescription, ...] = Field(min_length=1)

    @property
    def label(self) -> str:
        """How the athlete and the coach name it."""
        return f"Week {self.week} Treino {self.day}"


class ProgramDef(BaseModel):
    """A whole program file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    sessions_per_week_target: int = Field(default=3, ge=1, le=14)
    sessions: tuple[ProgramSession, ...] = Field(min_length=1)


def load_program(path: Path, index: ExerciseIndex) -> ProgramDef:
    """Read and validate a program file; every exercise must be in the library."""
    program = ProgramDef.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    unknown = sorted(
        {
            p.exercise
            for s in program.sessions
            for p in s.exercises
            if index.resolve(p.exercise) is None
        }
    )
    if unknown:
        raise ValueError(f"exercises missing from the library: {', '.join(unknown)}")
    return program
