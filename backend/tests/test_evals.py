from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from coach.core.evals import EvalCase, flatten, load_set, predict, score_case, summarize
from coach.core.registry import Registry
from coach.modules.gym.library import normalize
from coach.modules.gym.module import GymModule
from tests.fakes import scripted

pytestmark = pytest.mark.anyio

GYM_SET = Path(__file__).parents[1] / "src/coach/modules/gym/evals/extraction.yaml"


def test_flatten_keys_lifts_by_exercise_and_drops_empty_values() -> None:
    args = {
        "day": "B",
        "rpe": 8,
        "notes": "x",
        "started_at": "2026-10-06T07:00",
        "lifts": [
            {"exercise": "Agachamento Terra Sumo", "load_kg": 24, "skipped": False, "reps": None}
        ],
    }

    assert flatten(args, normalize) == {
        "day": "b",
        "rpe": "8.0",
        "lifts[agachamento terra sumo].exercise": "agachamento terra sumo",
        "lifts[agachamento terra sumo].load_kg": "24.0",
    }


def test_score_counts_correct_missing_and_invented_fields() -> None:
    case = EvalCase(id="c", input="x", expected={"day": "A", "rpe": 7})

    score = score_case(
        case,
        "log_gym_session",
        [{"name": "log_gym_session", "args": {"day": "A", "duration_min": 40}}],
        normalize,
    )

    assert score.tool_ok
    assert (score.precision, score.recall) == (0.5, 0.5)
    assert score.hallucinated == ["duration_min"]


def test_a_case_that_must_not_log_fails_when_it_logs() -> None:
    case = EvalCase(id="c", input="how many sessions this week?", expected=None)

    logged = score_case(
        case, "log_gym_session", [{"name": "log_gym_session", "args": {}}], normalize
    )
    asked = score_case(case, "log_gym_session", [{"name": "get_program", "args": {}}], normalize)

    assert (logged.tool_ok, asked.tool_ok) == (False, True)


def test_the_gym_set_has_sixteen_cases() -> None:
    eval_set = load_set(GYM_SET)

    assert eval_set.tool == "log_gym_session"
    assert len(eval_set.cases) == 16
    assert len({c.id for c in eval_set.cases}) == 16


async def test_predict_takes_the_models_first_reply() -> None:
    model = scripted(
        AIMessage(
            content="", tool_calls=[{"name": "log_gym_session", "args": {"day": "A"}, "id": "e1"}]
        )
    )
    case = EvalCase(id="one", input="did A", expected={"day": "A"})

    predictions = await predict(model, Registry([GymModule()]), [case])

    assert predictions == {"one": [{"name": "log_gym_session", "args": {"day": "A"}}]}


def test_summary_averages_cases() -> None:
    case = EvalCase(id="c", input="x", expected={"day": "A"})
    good = score_case(case, "t", [{"name": "t", "args": {"day": "A"}}], normalize)
    bad = score_case(case, "t", [], normalize)

    assert summarize([good, bad]) == {
        "cases": 2,
        "tool_accuracy": 0.5,
        "precision": 0.5,
        "recall": 0.5,
        "hallucinated": 0,
    }


def test_a_recording_from_a_different_prompt_or_schema_is_stale() -> None:
    from coach.core.evals import StaleRecordingError, check_recording, fingerprint

    current = fingerprint(Registry([GymModule()]))

    check_recording({"fingerprint": current}, current)
    with pytest.raises(StaleRecordingError):
        check_recording({"fingerprint": "something-older"}, current)
    with pytest.raises(StaleRecordingError):
        check_recording({}, current)


def test_scores_below_the_bar_fail() -> None:
    from coach.core.evals import below_thresholds

    assert below_thresholds({"tool_accuracy": 0.9, "recall": 0.85}) == []
    assert below_thresholds({"tool_accuracy": 0.7, "recall": 0.6}) == [
        "tool_accuracy 0.70 < 0.80",
        "recall 0.60 < 0.80",
    ]
