import pytest

from coach.core.db import Connection
from coach.core.models import Athlete, Location
from coach.modules.surf.seed import seed_spots
from coach.modules.surf.spots import (
    SPOTS_PATH,
    add_alias,
    create_spot,
    list_spots,
    load_spots,
    resolve_spot,
)

pytestmark = pytest.mark.anyio


def test_the_four_favourites_ship_with_profiles() -> None:
    spots = {s.name: s for s in load_spots(SPOTS_PATH)}

    assert set(spots) == {"Burleigh Heads", "Snapper Rocks", "Currumbin Alley", "Duranbah"}
    assert all(s.favourite and s.offshore_from and s.swell_from for s in spots.values())


async def test_seeding_is_idempotent(conn: Connection, athlete: Athlete) -> None:
    spots = load_spots(SPOTS_PATH)

    assert await seed_spots(conn, athlete, spots) == 4
    assert await seed_spots(conn, athlete, spots) == 4
    assert len(await list_spots(conn, athlete)) == 4


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("burleigh", "Burleigh Heads"),
        ("Snapper", "Snapper Rocks"),
        ("superbank", "Snapper Rocks"),
        ("the alley", "Currumbin Alley"),
        ("D'Bah", "Duranbah"),
        ("dbah", "Duranbah"),
        ("d bah", "Duranbah"),
        ("burleigh heds", "Burleigh Heads"),
        ("kirra", None),
    ],
)
async def test_spot_names_resolve_with_aliases_and_typos(
    conn: Connection, athlete: Athlete, said: str, expected: str | None
) -> None:
    await seed_spots(conn, athlete, load_spots(SPOTS_PATH))

    spot = await resolve_spot(conn, athlete, said)

    assert (spot["name"] if spot else None) == expected


async def test_new_spots_and_aliases(conn: Connection, athlete: Athlete) -> None:
    await seed_spots(conn, athlete, load_spots(SPOTS_PATH))

    kirra = await create_spot(conn, athlete, "Kirra", Location(-28.167, 153.531))
    burleigh = await resolve_spot(conn, athlete, "burleigh")
    assert burleigh is not None
    await add_alias(conn, burleigh["id"], "the point")

    found_kirra = await resolve_spot(conn, athlete, "kirra")
    found_point = await resolve_spot(conn, athlete, "the point")
    assert found_kirra is not None and found_kirra["id"] == kirra["id"]
    assert found_point is not None and found_point["name"] == "Burleigh Heads"
