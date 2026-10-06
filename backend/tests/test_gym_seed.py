from pathlib import Path

import pytest

from coach.core.db import Connection
from coach.core.models import Athlete
from coach.modules.gym.library import ExerciseIndex, library_index, load_library, normalize
from coach.modules.gym.program import load_program
from coach.modules.gym.seed import ProgramConflictError, main, seed_program

SAMPLE = Path(__file__).parents[1] / "src/coach/modules/gym/programs/sample.yaml"


def test_normalize_ignores_case_accents_and_punctuation() -> None:
    assert normalize("Cócoras") == "cocoras"
    assert normalize("  SL SQUAT - Estabilidade ") == "sl squat estabilidade"
    assert normalize("90/90 com intenção") == "90/90 com intencao"


def test_library_resolves_portuguese_names_and_english_aliases() -> None:
    index = library_index()

    goblet = index.resolve("agachamento goblet")
    assert goblet is not None
    assert index.resolve("Goblet squat") == goblet
    assert index.resolve("serrote") == index.resolve("one arm dumbbell row")
    assert index.resolve("cocoras") is not None
    assert index.resolve("bulgarian bag spin") is None


def test_library_rejects_an_alias_used_by_two_exercises(tmp_path: Path) -> None:
    path = tmp_path / "lib.yaml"
    path.write_text(
        "exercises:\n"
        "  - {name: One, aliases: [shared], pattern: core}\n"
        "  - {name: Two, aliases: [shared], pattern: core}\n"
    )

    with pytest.raises(ValueError, match="shared"):
        ExerciseIndex(load_library(path))


def test_sample_program_loads() -> None:
    program = load_program(SAMPLE, library_index())

    assert [s.label for s in program.sessions] == [
        "Week 1 Treino A",
        "Week 1 Treino B",
        "Week 2 Treino A",
        "Week 2 Treino B",
    ]
    assert {p.block for s in program.sessions for p in s.exercises} == {"prep", "main"}


def test_unknown_exercises_are_named(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        "name: Bad\nsessions:\n  - week: 1\n    day: A\n    exercises:\n"
        "      - {exercise: Moonwalk, block: main, sets: 3, reps: '10'}\n"
    )

    with pytest.raises(ValueError, match="Moonwalk"):
        load_program(path, library_index())


@pytest.mark.anyio
async def test_seed_writes_the_program_in_order(conn: Connection, athlete: Athlete) -> None:
    program = load_program(SAMPLE, library_index())

    program_id = await seed_program(
        conn, athlete, program, library_index(), source_file="sample.yaml"
    )

    cur = await conn.execute(
        "select ps.position, ps.label, count(pe.id)::int as exercises from program_sessions ps "
        "join program_exercises pe on pe.program_session_id = ps.id "
        "where ps.program_id = %s group by ps.position, ps.label order by ps.position",
        (program_id,),
    )
    rows = await cur.fetchall()
    assert [r["label"] for r in rows] == [s.label for s in program.sessions]
    assert [r["exercises"] for r in rows] == [len(s.exercises) for s in program.sessions]


@pytest.mark.anyio
async def test_reseeding_needs_replace(conn: Connection, athlete: Athlete) -> None:
    program = load_program(SAMPLE, library_index())
    first = await seed_program(conn, athlete, program, library_index(), source_file="a.yaml")

    with pytest.raises(ProgramConflictError, match=r"a\.yaml"):
        await seed_program(conn, athlete, program, library_index(), source_file="b.yaml")
    second = await seed_program(
        conn, athlete, program, library_index(), source_file="b.yaml", replace=True
    )

    cur = await conn.execute("select id, active from programs where athlete_id = %s", (athlete.id,))
    assert {(r["id"], r["active"]) for r in await cur.fetchall()} == {
        (first, False),
        (second, True),
    }


def test_check_mode_validates_without_a_database(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--program", str(SAMPLE), "--check"])

    assert "4 sessions over 2 weeks" in capsys.readouterr().out
