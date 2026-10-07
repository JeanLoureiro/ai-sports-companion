from datetime import datetime
from typing import Any

import httpx
import pytest

from coach.modules.surf.forecast import (
    MARINE_URL,
    ForecastError,
    Hour,
    Spot,
    compass,
    fetch_hours,
    in_range,
    rate,
    tide_events,
    wind_relation,
    windows,
)

pytestmark = pytest.mark.anyio

SNAPPER = Spot(
    name="Snapper Rocks",
    latitude=-28.16,
    longitude=153.55,
    swell_from=(60, 170),
    offshore_from=(200, 290),
    min_swell_m=0.6,
)
NORTHERLY = Spot(
    name="Wrap", latitude=0, longitude=0, swell_from=None, offshore_from=(300, 30), min_swell_m=None
)


def hour(at: str, **values: float) -> Hour:
    base: dict[str, Any] = {
        "swell_m": 1.0,
        "period_s": 9.0,
        "swell_from": 100.0,
        "wind_kn": 5.0,
        "wind_from": 250.0,
        "sea_level_m": 0.0,
    }
    base.update(values)
    return Hour(time=datetime.fromisoformat(at), **base)


def test_compass_points() -> None:
    assert [compass(d) for d in (0, 44, 90, 202, 355)] == ["N", "NE", "E", "SSW", "N"]


def test_ranges_wrap_past_north() -> None:
    assert in_range(350, 300, 30) and in_range(10, 300, 30)
    assert not in_range(180, 300, 30)
    assert in_range(100, 60, 170) and not in_range(200, 60, 170)


def test_wind_relation_uses_the_spot_profile() -> None:
    assert wind_relation(SNAPPER, 245) == "offshore"
    assert wind_relation(SNAPPER, 65) == "onshore"
    assert wind_relation(SNAPPER, 160) == "cross-shore"
    assert wind_relation(NORTHERLY, 0) == "offshore"
    assert wind_relation(Spot("x", 0, 0, None, None, None), 90) == "unknown"


def test_rating_rewards_size_period_direction_and_offshore_wind() -> None:
    perfect = hour(
        "2026-10-08T06:00", swell_m=1.2, period_s=11, swell_from=110, wind_kn=8, wind_from=250
    )
    blown_out = hour(
        "2026-10-08T14:00", swell_m=1.2, period_s=11, swell_from=110, wind_kn=18, wind_from=60
    )
    flat = hour("2026-10-08T06:00", swell_m=0.3, swell_from=20)

    assert (rate(SNAPPER, perfect), rate(SNAPPER, blown_out), rate(SNAPPER, flat)) == (5, 3, 1)


def test_tide_events_are_local_extremes() -> None:
    levels = [0.0, 0.4, 0.8, 0.6, 0.2, -0.3, -0.1, 0.3]
    hours = [hour(f"2026-10-08T{h:02d}:00", sea_level_m=lv) for h, lv in enumerate(levels)]

    assert [(e["time"], e["kind"]) for e in tide_events(hours)] == [
        ("2026-10-08 02:00", "high"),
        ("2026-10-08 05:00", "low"),
    ]


def test_windows_pick_the_best_hour_per_part_of_the_day() -> None:
    hours = [
        hour("2026-10-08T05:00", wind_kn=15, wind_from=60, sea_level_m=0.1),
        hour("2026-10-08T07:00", wind_kn=4, wind_from=250, sea_level_m=0.3),
        hour("2026-10-08T15:00", wind_kn=20, wind_from=60, sea_level_m=0.5),
    ]

    morning, afternoon = windows(SNAPPER, hours)

    assert (morning["window"], morning["time"], morning["wind"]) == ("morning", "07:00", "offshore")
    assert morning["tide"] == "rising"
    assert morning["swell_ft"] == 3.3
    assert afternoon["window"] == "afternoon"


def payloads(swell: list[float | None]) -> dict[str, dict[str, Any]]:
    times = [f"2026-10-08T{h:02d}:00" for h in range(len(swell))]
    marine = {
        "hourly": {
            "time": times,
            "swell_wave_height": swell,
            "swell_wave_period": [9.0] * len(swell),
            "swell_wave_direction": [100.0] * len(swell),
            "sea_level_height_msl": [0.1] * len(swell),
        }
    }
    weather = {
        "hourly": {
            "time": times,
            "wind_speed_10m": [5.0] * len(swell),
            "wind_direction_10m": [250.0] * len(swell),
        }
    }
    return {"marine": marine, "weather": weather}


def client(data: dict[str, dict[str, Any]], status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        key = "marine" if str(request.url).startswith(MARINE_URL) else "weather"
        return httpx.Response(status, json=data[key])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_skips_hours_with_gaps() -> None:
    hours = await fetch_hours(
        client(payloads([1.0, None, 1.2])), SNAPPER, days=1, timezone="Australia/Brisbane"
    )

    assert [h.time.hour for h in hours] == [0, 2]


async def test_fetch_reports_http_failures() -> None:
    with pytest.raises(ForecastError):
        await fetch_hours(
            client(payloads([1.0]), status=502), SNAPPER, days=1, timezone="Australia/Brisbane"
        )
