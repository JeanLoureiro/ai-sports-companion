"""Gym tools bound to the agent."""

import json
from datetime import datetime
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import BaseModel, ConfigDict, Field

from coach.core.context import CoachContext
from coach.core.db import Connection
from coach.core.models import Athlete, ReplyButton
from coach.core.repo import create_session, session_for_call
from coach.core.tools import history_window
from coach.modules.gym.library import ExerciseIndex, library_index, normalize
from coach.modules.gym.repo import (
    active_program,
    complete_program_session,
    day_labels,
    done_since,
    insert_details,
    next_pending,
    prescriptions,
    progress,
)


async def program_summary(
    conn: Connection, athlete: Athlete, now: datetime
) -> dict[str, Any] | None:
    """Progress, this week against the target, and the next session in full."""
    program = await active_program(conn, athlete)
    if program is None:
        return None
    week_start, _ = history_window("this_week", 7, now, athlete.timezone)
    upcoming = await next_pending(conn, program["id"])
    next_session = None
    if upcoming is not None:
        next_session = {
            "position": upcoming["position"],
            "label": upcoming["label"],
            "planned_date": upcoming["planned_date"],
            "exercises": await prescriptions(conn, upcoming["id"]),
        }
    return {
        "program": program["name"],
        "progress": await progress(conn, program["id"]),
        "this_week": {
            "done": await done_since(conn, program["id"], week_start),
            "target": program["sessions_per_week_target"],
        },
        "next_session": next_session,
    }


@tool
async def get_program(runtime: ToolRuntime[CoachContext]) -> str:
    """The athlete's gym program: progress, sessions done this week against the target, and the
    next pending session with every exercise as prescribed (sets, reps, rest in seconds, tempo
    as cadência such as 4.0.X.0, and notes). Use it for "what's my next session?"."""
    ctx = runtime.context
    async with ctx.pool.connection() as conn:
        summary = await program_summary(conn, ctx.athlete, ctx.now())
    if summary is None:
        summary = {"program": None, "message": "No active gym program has been seeded."}
    return json.dumps(summary, default=str, ensure_ascii=False)


class LiftLog(BaseModel):
    """One exercise the athlete mentioned. Fill only what they said."""

    # Unknown fields (e.g. rpe inside a lift) must fail loudly, not vanish.
    model_config = ConfigDict(extra="forbid")

    exercise: str = Field(description="As the athlete said it, Portuguese or English")
    load_kg: float | None = Field(default=None, ge=0, description="Dumbbell weight in kg")
    sets: int | None = Field(default=None, ge=1)
    reps: str | None = None
    swapped_to: str | None = Field(default=None, description="What they did instead")
    skipped: bool = False


def merge_lifts(
    planned: list[dict[str, Any]], lifts: list[LiftLog], index: ExerciseIndex
) -> list[dict[str, Any]]:
    """Main-block exercises as prescribed, overridden by what the athlete mentioned.

    Prep exercises are stored only when mentioned; unknown exercises are kept as said.
    """
    planned_names = [p["exercise"] for p in planned]
    mentioned: dict[str, tuple[str, LiftLog, bool]] = {}
    for lift in lifts:
        name, known = _resolve(lift.exercise, planned_names, index)
        mentioned[normalize(name)] = (name, lift, known)
    entries: list[dict[str, Any]] = []
    for p in planned:
        said = mentioned.pop(normalize(p["exercise"]), None)
        if p["block"] != "main" and said is None:
            continue
        entry: dict[str, Any] = {
            "exercise": p["exercise"],
            "planned": {"sets": p["sets"], "reps": p["reps"], "tempo": p["tempo"]},
            "done": True,
        }
        if said is not None:
            entry.update(_said(said[1], index))
        entries.append(entry)
    for name, lift, is_known in mentioned.values():
        entries.append({"exercise": name, "extra": True, "known": is_known, **_said(lift, index)})
    return entries


def _said(lift: LiftLog, index: ExerciseIndex) -> dict[str, Any]:
    out: dict[str, Any] = {"done": not lift.skipped}
    if lift.load_kg is not None:
        out["load_kg"] = lift.load_kg
    if lift.sets is not None:
        out["sets"] = lift.sets
    if lift.reps is not None:
        out["reps"] = lift.reps
    if lift.swapped_to is not None:
        swapped = index.resolve(lift.swapped_to)
        out["swapped_to"] = swapped.name if swapped else lift.swapped_to
    return out


def _tokens(text: str) -> set[str]:
    return {w.removesuffix("s") if len(w) > 3 else w for w in normalize(text).split()}


def _resolve(name: str, planned: list[str], index: ExerciseIndex) -> tuple[str, bool]:
    """Prefer the session being logged ("rows" on Treino B is its row), then the library.

    A planned exercise matches when every word said appears in its name or one alias, and
    only a unique match counts; otherwise the library decides, and unknown names stay as said.
    """
    said = _tokens(name)
    matches = []
    for planned_name in planned:
        exercise = index.resolve(planned_name)
        keys = [planned_name, *(exercise.aliases if exercise else ())]
        if said and any(said <= _tokens(key) for key in keys):
            matches.append(planned_name)
    if len(matches) == 1:
        return matches[0], True
    known = index.resolve(name)
    return (known.name, True) if known else (name, False)


_DAY_WORDS = {"treino", "session", "sessao", "day", "dia", "workout"}


def _day_label(day: str) -> str | None:
    """'Treino B', 'b', 'session C' -> 'B', 'C'; anything else -> None."""
    words = [w for w in normalize(day).split() if w not in _DAY_WORDS]
    return words[0].upper() if len(words) == 1 and len(words[0]) == 1 else None


@tool
async def log_gym_session(
    runtime: ToolRuntime[CoachContext],
    day: Annotated[
        str | None,
        Field(
            description="Required. The session the athlete named ('Treino B', 'B', "
            "'session C' -> A, B or C), or null only if they did not name one. Always pass "
            "it when named: without it the next pending session is completed."
        ),
    ],
    started_at: Annotated[
        datetime | None, Field(description="Local date and time; omit for now")
    ] = None,
    duration_min: Annotated[int | None, Field(ge=1, le=600)] = None,
    rpe: Annotated[int | None, Field(ge=1, le=10)] = None,
    notes: Annotated[str | None, Field(description="Anything else, in their words")] = None,
    lifts: list[LiftLog] | None = None,
) -> str:
    """Log one gym session against the program. Everything not mentioned counts as done as
    prescribed. Without a day, it completes the next pending session; with a day, the first
    pending session for that day. Call once per session."""
    ctx = runtime.context
    index = library_index()
    label_day = _day_label(day) if day else None
    async with ctx.pool.connection() as conn, conn.transaction():
        already = await session_for_call(conn, ctx.athlete, runtime.tool_call_id)
        if already is not None:
            return f"Already logged by this call (session {already})."
        program = await active_program(conn, ctx.athlete)
        planned = None
        if program is not None:
            if day:
                labels = await day_labels(conn, program["id"])
                if label_day not in labels:
                    raise ValueError(
                        f"Unknown day {day!r}: this program's days are {', '.join(labels)}. "
                        "Ask the athlete which session they did."
                    )
            planned = await next_pending(conn, program["id"], day_label=label_day)
        planned_rows = await prescriptions(conn, planned["id"]) if planned else []
        entries = merge_lifts(planned_rows, lifts or [], index)
        label = planned["label"] if planned else "Extra gym session"
        session_id = await create_session(
            conn,
            ctx.athlete,
            discipline="gym",
            started_at=ctx.local_to_utc(started_at),
            duration_min=duration_min,
            rpe=rpe,
            summary=label,
            call_id=runtime.tool_call_id,
        )
        await insert_details(conn, session_id, planned["id"] if planned else None, entries, notes)
        if planned is not None:
            await complete_program_session(conn, planned["id"], session_id)
        total = (await progress(conn, program["id"]))["total"] if program else 0
    ctx.reply_buttons.append(ReplyButton(text="Undo", data=f"undo:{session_id}"))
    changed = [e for e in entries if set(e) - {"exercise", "planned", "done"} or not e["done"]]
    detail = json.dumps(changed, ensure_ascii=False) if changed else "everything as prescribed"
    if planned is None:
        if label_day:
            reason = f"no pending Treino {label_day} left"
        else:
            reason = "the program is complete" if program else "no active program"
        return f"Logged as an extra session ({reason}). Changes: {detail}. Notes: {notes or '-'}"
    return (
        f"Logged {label} (session {planned['position']} of {total}). "
        f"Changes: {detail}. Notes: {notes or '-'}"
    )
