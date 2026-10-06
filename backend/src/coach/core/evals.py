"""Tool-call extraction evals: ``python -m coach.core.evals``.

Each module lists YAML eval sets in ``evals()``. Live mode asks the model once per case and
can record its answers to ``recordings/<set>.json``; replay mode scores those recordings, so CI
needs no API key.
"""

import argparse
import asyncio
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from coach.core.models import Athlete
from coach.core.prompt import system_prompt
from coach.core.registry import Registry
from coach.core.tools import CORE_TOOLS

type Normalizer = Callable[[str], str]

EVAL_ATHLETE = Athlete(
    id=UUID(int=0), name="Eval Athlete", timezone="Australia/Brisbane", telegram_chat_id=None
)
EVAL_NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
IGNORED_FIELDS = {"started_at", "notes"}
MIN_TOOL_ACCURACY = 0.8
MIN_RECALL = 0.8


class StaleRecordingError(Exception):
    """A recording was made with a different system prompt or tool schema."""


def fingerprint(registry: Registry) -> str:
    """A short hash of everything the model sees: system prompt and every tool schema."""
    payload = {
        "system": system_prompt(EVAL_ATHLETE, registry, "", EVAL_NOW),
        "tools": [convert_to_openai_tool(t) for t in [*CORE_TOOLS, *registry.tools()]],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    return sha256(encoded).hexdigest()[:16]


def check_recording(recording: dict[str, Any], current: str) -> None:
    """Refuse to score answers the current prompt and tools would not have produced."""
    if recording.get("fingerprint") != current:
        raise StaleRecordingError(
            "the recording was made with a different prompt or tool schema; "
            "re-record with --mode live --record"
        )


def below_thresholds(summary: dict[str, Any]) -> list[str]:
    """Scores under the bar, as readable lines; empty when the set passes."""
    failures = []
    for key, minimum in (("tool_accuracy", MIN_TOOL_ACCURACY), ("recall", MIN_RECALL)):
        if summary[key] < minimum:
            failures.append(f"{key} {summary[key]:.2f} < {minimum:.2f}")
    return failures


class EvalCase(BaseModel):
    """One message and the arguments it should produce (None: the tool must not be called)."""

    id: str
    input: str
    expected: dict[str, Any] | None


class EvalSet(BaseModel):
    """A YAML file of cases for one tool."""

    name: str
    tool: str
    cases: list[EvalCase]
    path: Path


def load_set(path: Path) -> EvalSet:
    """Read an eval set; its name is the file stem."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return EvalSet(name=path.stem, tool=data["tool"], cases=data["cases"], path=path)


def flatten(value: Any, normalize: Normalizer, prefix: str = "") -> dict[str, str]:
    """Dotted paths to comparable strings; empty values and ignored fields are dropped."""
    out: dict[str, str] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if not prefix and key in IGNORED_FIELDS:
                continue
            out.update(flatten(item, normalize, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for position, item in enumerate(value):
            if isinstance(item, dict) and "exercise" in item:
                key = normalize(str(item["exercise"]))
            else:
                key = str(position)
            out.update(flatten(item, normalize, f"{prefix}[{key}]"))
    elif value is None or value is False or value == []:
        pass
    elif value is True:
        out[prefix] = "true"
    elif isinstance(value, int | float):
        out[prefix] = str(float(value))
    else:
        text = str(value)
        try:
            out[prefix] = str(float(text))
        except ValueError:
            out[prefix] = normalize(text)
    return out


@dataclass(frozen=True, slots=True)
class CaseScore:
    """How one case went."""

    case_id: str
    tool_ok: bool
    precision: float
    recall: float
    hallucinated: list[str]


def score_case(
    case: EvalCase, tool: str, calls: list[dict[str, Any]], normalize: Normalizer
) -> CaseScore:
    """Compare the first call to ``tool`` with the expectation."""
    call = next((c for c in calls if c["name"] == tool), None)
    if case.expected is None:
        return CaseScore(case.id, call is None, 1.0, 1.0, [])
    if call is None:
        return CaseScore(case.id, False, 0.0, 0.0, [])
    expected = flatten(case.expected, normalize)
    predicted = flatten(call["args"], normalize)
    correct = [k for k, v in expected.items() if predicted.get(k) == v]
    precision = len(correct) / len(predicted) if predicted else 1.0
    recall = len(correct) / len(expected) if expected else 1.0
    hallucinated = sorted(k for k in predicted if k not in expected)
    return CaseScore(case.id, True, precision, recall, hallucinated)


def summarize(scores: Sequence[CaseScore]) -> dict[str, Any]:
    """Averages across cases."""
    n = len(scores)
    return {
        "cases": n,
        "tool_accuracy": sum(s.tool_ok for s in scores) / n,
        "precision": sum(s.precision for s in scores) / n,
        "recall": sum(s.recall for s in scores) / n,
        "hallucinated": sum(len(s.hallucinated) for s in scores),
    }


async def predict(
    model: BaseChatModel, registry: Registry, cases: Sequence[EvalCase]
) -> dict[str, list[dict[str, Any]]]:
    """Ask the model once per case, with every tool bound and the real system prompt."""
    bound = model.bind_tools([*CORE_TOOLS, *registry.tools()])
    system = SystemMessage(system_prompt(EVAL_ATHLETE, registry, "", EVAL_NOW))
    out: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        reply = await bound.ainvoke([system, HumanMessage(case.input)])
        calls = reply.tool_calls if isinstance(reply, AIMessage) else []
        out[case.id] = [{"name": c["name"], "args": c["args"]} for c in calls]
    return out


def recording_path(eval_set: EvalSet) -> Path:
    """Where a set's recorded model answers live."""
    return eval_set.path.parent / "recordings" / f"{eval_set.name}.json"


async def _run(args: argparse.Namespace) -> None:
    from coach.core.config import get_settings
    from coach.core.db import create_pool
    from coach.core.llm import get_chat_model
    from coach.core.registry import default_registry
    from coach.modules.gym.library import normalize  # the only normalizer so far

    registry = default_registry()
    current = fingerprint(registry)
    results: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for module in registry.modules:
        for path in module.evals():
            eval_set = load_set(path)
            recording = recording_path(eval_set)
            if args.mode == "live":
                settings = get_settings()
                predictions = await predict(get_chat_model(settings), registry, eval_set.cases)
                if args.record:
                    recording.parent.mkdir(parents=True, exist_ok=True)
                    recording.write_text(
                        json.dumps(
                            {
                                "model": settings.agent_model,
                                "fingerprint": current,
                                "cases": predictions,
                            },
                            indent=2,
                            ensure_ascii=False,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
            else:
                if not recording.exists():
                    raise SystemExit(
                        f"No recording for {eval_set.name}; run with --mode live --record"
                    )
                recorded = json.loads(recording.read_text(encoding="utf-8"))
                try:
                    check_recording(recorded, current)
                except StaleRecordingError as err:
                    raise SystemExit(f"{eval_set.name}: {err}") from err
                predictions = recorded["cases"]
            scores = [
                score_case(c, eval_set.tool, predictions.get(c.id, []), normalize)
                for c in eval_set.cases
            ]
            results[eval_set.name] = summarize(scores)
            print(f"{module.name}/{eval_set.name}: {json.dumps(results[eval_set.name])}")
            failures += [f"{eval_set.name}: {f}" for f in below_thresholds(results[eval_set.name])]
            for s in scores:
                if not s.tool_ok or s.recall < 1 or s.hallucinated:
                    print(
                        f"  {s.case_id}: tool_ok={s.tool_ok} recall={s.recall:.2f} "
                        f"invented={s.hallucinated}"
                    )
    if args.save_run:
        pool = create_pool(get_settings().database_url.get_secret_value())
        await pool.open()
        try:
            async with pool.connection() as conn:
                await conn.execute(
                    "insert into eval_runs (dataset, mode, git_sha, model, metrics) "
                    "values ('synthetic', %s, %s, %s, %s)",
                    (
                        args.mode,
                        os.environ.get("GITHUB_SHA"),
                        get_settings().agent_model,
                        Jsonb(results),
                    ),
                )
        finally:
            await pool.close()
    if failures:
        raise SystemExit("Evals below the bar:\n" + "\n".join(failures))


def main(argv: Sequence[str] | None = None) -> None:
    """Run every enabled module's eval sets."""
    parser = argparse.ArgumentParser(prog="python -m coach.core.evals")
    parser.add_argument("--mode", choices=["replay", "live"], default="replay")
    parser.add_argument("--record", action="store_true", help="live: write recordings")
    parser.add_argument("--save-run", action="store_true", help="write eval_runs")
    asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    main()
