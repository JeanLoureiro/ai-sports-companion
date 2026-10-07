"""Spot profiles and resolving spot names said in chat."""

import difflib
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict

from coach.core.db import Connection
from coach.core.models import Athlete, Location
from coach.core.text import normalize

SPOTS_PATH = Path(__file__).parent / "spots.yaml"
_SELECT = (
    "select id, name, aliases, latitude, longitude, swell_from_min, swell_from_max, "
    "offshore_from_min, offshore_from_max, min_swell_m, favourite from surf_spots "
)


class SpotDef(BaseModel):
    """One spot as written in spots.yaml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    aliases: tuple[str, ...] = ()
    latitude: float
    longitude: float
    swell_from: tuple[int, int] | None = None
    offshore_from: tuple[int, int] | None = None
    min_swell_m: float | None = None
    favourite: bool = False


def load_spots(path: Path) -> list[SpotDef]:
    """Read ``spots:`` from a YAML file."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [SpotDef.model_validate(item) for item in data["spots"]]


def spot_keys(row: dict[str, Any]) -> list[str]:
    """Every normalized name a spot answers to, spaces removed too ('d bah' and 'dbah')."""
    keys = [normalize(k) for k in (row["name"], *row["aliases"])]
    return [*keys, *(k.replace(" ", "") for k in keys)]


async def list_spots(conn: Connection, athlete: Athlete) -> list[dict[str, Any]]:
    """The athlete's spots, favourites first."""
    cur = await conn.execute(
        _SELECT + "where athlete_id = %s order by favourite desc, name", (athlete.id,)
    )
    return await cur.fetchall()


async def resolve_spot(
    conn: Connection, athlete: Athlete, said: str, *, fuzzy: bool = True
) -> dict[str, Any] | None:
    """Exact name or alias first, then (if ``fuzzy``) a single close match; otherwise None."""
    wanted = normalize(said)
    if not wanted:
        return None
    by_key: dict[str, dict[str, Any]] = {}
    for spot in await list_spots(conn, athlete):
        for key in spot_keys(spot):
            by_key.setdefault(key, spot)
    for key in (wanted, wanted.replace(" ", "")):
        if key in by_key:
            return by_key[key]
    if not fuzzy:
        return None
    close = {
        by_key[k]["id"]: by_key[k] for k in difflib.get_close_matches(wanted, by_key, cutoff=0.85)
    }
    return next(iter(close.values())) if len(close) == 1 else None


async def create_spot(
    conn: Connection, athlete: Athlete, name: str, location: Location
) -> dict[str, Any]:
    """A new spot from a location pin, without a profile yet."""
    await conn.execute(
        "insert into surf_spots (athlete_id, name, latitude, longitude) values (%s, %s, %s, %s) "
        "on conflict (athlete_id, name) do update set latitude = excluded.latitude, "
        "longitude = excluded.longitude",
        (athlete.id, name, location.latitude, location.longitude),
    )
    cur = await conn.execute(_SELECT + "where athlete_id = %s and name = %s", (athlete.id, name))
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError("spot insert returned no row")
    return row


async def add_alias(conn: Connection, spot_id: UUID, alias: str) -> None:
    """Remember another name for a spot."""
    await conn.execute(
        "update surf_spots set aliases = array_append(aliases, %s) "
        "where id = %s and not (%s = any(aliases))",
        (alias, spot_id, alias),
    )
