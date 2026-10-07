"""Load spot profiles for an athlete: ``python -m coach.modules.surf.seed``."""

import argparse
import asyncio
from collections.abc import Sequence

from coach.core.config import get_settings
from coach.core.db import Connection, create_pool
from coach.core.models import Athlete
from coach.core.repo import get_athlete_by_chat_id
from coach.modules.surf.spots import SPOTS_PATH, SpotDef, load_spots


async def seed_spots(conn: Connection, athlete: Athlete, spots: Sequence[SpotDef]) -> int:
    """Upsert every spot by name, profile included; returns how many were written."""
    async with conn.transaction():
        for spot in spots:
            swell = spot.swell_from or (None, None)
            offshore = spot.offshore_from or (None, None)
            await conn.execute(
                "insert into surf_spots (athlete_id, name, aliases, latitude, longitude, "
                "favourite, swell_from_min, swell_from_max, offshore_from_min, "
                "offshore_from_max, min_swell_m) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "on conflict (athlete_id, name) do update set aliases = array(select distinct "
                "unnest(surf_spots.aliases || excluded.aliases)), "
                "latitude = excluded.latitude, longitude = excluded.longitude, "
                "favourite = excluded.favourite, swell_from_min = excluded.swell_from_min, "
                "swell_from_max = excluded.swell_from_max, "
                "offshore_from_min = excluded.offshore_from_min, "
                "offshore_from_max = excluded.offshore_from_max, "
                "min_swell_m = excluded.min_swell_m",
                (
                    athlete.id,
                    spot.name,
                    list(spot.aliases),
                    spot.latitude,
                    spot.longitude,
                    spot.favourite,
                    swell[0],
                    swell[1],
                    offshore[0],
                    offshore[1],
                    spot.min_swell_m,
                ),
            )
    return len(spots)


async def _seed(chat_id: int) -> None:
    pool = create_pool(get_settings().database_url.get_secret_value())
    await pool.open()
    try:
        async with pool.connection() as conn:
            athlete = await get_athlete_by_chat_id(conn, chat_id)
            if athlete is None:
                raise SystemExit(f"No athlete for chat {chat_id}; run `coach add-athlete` first.")
            count = await seed_spots(conn, athlete, load_spots(SPOTS_PATH))
        print(f"Seeded {count} spots for {athlete.name}")
    finally:
        await pool.close()


def main(argv: Sequence[str] | None = None) -> None:
    """Seed the shipped spot profiles for an athlete."""
    parser = argparse.ArgumentParser(prog="python -m coach.modules.surf.seed")
    parser.add_argument("--chat-id", type=int, required=True)
    asyncio.run(_seed(parser.parse_args(argv).chat_id))


if __name__ == "__main__":
    main()
