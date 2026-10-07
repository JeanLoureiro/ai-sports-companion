"""Open-Meteo forecasts, rated against a spot's profile. Every number is an estimate."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import httpx

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
FT_PER_M = 3.28084
ESTIMATE_NOTE = (
    "Estimates from Open-Meteo's regional model: nearby spots share the same swell and tide "
    "numbers; ratings come from each spot's profile (swell direction, offshore wind)."
)
_POINTS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)  # fmt: skip
_WINDOWS = (("morning", 5, 9), ("midday", 10, 13), ("afternoon", 14, 18))

type WindRelation = Literal["offshore", "cross-shore", "onshore", "unknown"]


class ForecastError(RuntimeError):
    """Open-Meteo could not be reached or answered with an error."""


@dataclass(frozen=True, slots=True)
class Spot:
    """What the rating needs to know about a spot."""

    name: str
    latitude: float
    longitude: float
    swell_from: tuple[int, int] | None
    offshore_from: tuple[int, int] | None
    min_swell_m: float | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Spot:
        """Build from a ``surf_spots`` row."""

        def pair(lo: Any, hi: Any) -> tuple[int, int] | None:
            return (int(lo), int(hi)) if lo is not None and hi is not None else None

        return cls(
            name=row["name"],
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            swell_from=pair(row["swell_from_min"], row["swell_from_max"]),
            offshore_from=pair(row["offshore_from_min"], row["offshore_from_max"]),
            min_swell_m=float(row["min_swell_m"]) if row["min_swell_m"] is not None else None,
        )


@dataclass(frozen=True, slots=True)
class Hour:
    """One forecast hour, local time."""

    time: datetime
    swell_m: float
    period_s: float
    swell_from: float
    wind_kn: float
    wind_from: float
    sea_level_m: float | None


def compass(degrees: float) -> str:
    """16-point compass name."""
    return _POINTS[round(degrees / 22.5) % 16]


def in_range(degrees: float, lo: int, hi: int) -> bool:
    """Whether a direction lies in [lo, hi], wrapping past north when lo > hi."""
    d = degrees % 360
    return lo <= d <= hi if lo <= hi else d >= lo or d <= hi


def angle_between(a: float, b: float) -> float:
    """Smallest angle between two directions."""
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)


def _centre(lo: int, hi: int) -> float:
    return (lo + ((hi - lo) % 360) / 2) % 360


def wind_relation(spot: Spot, wind_from: float) -> WindRelation:
    """Offshore within 45 degrees of the spot's offshore centre, onshore beyond 135."""
    if spot.offshore_from is None:
        return "unknown"
    gap = angle_between(wind_from, _centre(*spot.offshore_from))
    if gap <= 45:
        return "offshore"
    return "onshore" if gap >= 135 else "cross-shore"


def rate(spot: Spot, hour: Hour) -> int:
    """0 to 5: +2 size (+1 period of 10 s or more), +1 swell direction, +1 offshore or light
    wind, -1 onshore at 12 kn or more; all against the spot's profile."""
    score = 0
    if hour.swell_m >= (spot.min_swell_m or 0.5):
        score += 2
        if hour.period_s >= 10:
            score += 1
    if spot.swell_from is None or in_range(hour.swell_from, *spot.swell_from):
        score += 1
    relation = wind_relation(spot, hour.wind_from)
    if relation == "offshore" or hour.wind_kn < 6:
        score += 1
    elif relation == "onshore" and hour.wind_kn >= 12:
        score -= 1
    return max(0, min(5, score))


def tide_events(hours: list[Hour]) -> list[dict[str, Any]]:
    """Highs and lows as local extremes of the hourly sea level."""
    levels = [(h.time, h.sea_level_m) for h in hours if h.sea_level_m is not None]
    events = []
    for (_, before), (at, level), (_, after) in zip(levels, levels[1:], levels[2:], strict=False):
        if before < level >= after:
            kind = "high"
        elif before > level <= after:
            kind = "low"
        else:
            continue
        events.append({"time": f"{at:%Y-%m-%d %H:%M}", "kind": kind, "sea_level_m": level})
    return events


def _tide_trend(hours: list[Hour], at: Hour) -> str:
    """Rising or falling at an hour, from the next known sea level (else the previous one)."""
    if at.sea_level_m is None:
        return "unknown"
    position = hours.index(at)
    later = [h.sea_level_m for h in hours[position + 1 :] if h.sea_level_m is not None]
    if later:
        return "rising" if later[0] > at.sea_level_m else "falling"
    earlier = [h.sea_level_m for h in hours[:position] if h.sea_level_m is not None]
    if earlier:
        return "rising" if at.sea_level_m > earlier[-1] else "falling"
    return "unknown"


def windows(spot: Spot, hours: list[Hour]) -> list[dict[str, Any]]:
    """The best hour of each morning, midday and afternoon, day by day."""
    out = []
    for day in sorted({h.time.date() for h in hours}):
        for name, start, end in _WINDOWS:
            candidates = [h for h in hours if h.time.date() == day and start <= h.time.hour <= end]
            if not candidates:
                continue
            best = max(candidates, key=lambda h: (rate(spot, h), -h.time.hour))
            out.append(
                {
                    "day": f"{day:%a %d %b}",
                    "window": name,
                    "time": f"{best.time:%H:%M}",
                    "swell_m": round(best.swell_m, 1),
                    "swell_ft": round(best.swell_m * FT_PER_M, 1),
                    "period_s": round(best.period_s),
                    "swell_from": compass(best.swell_from),
                    "wind_kn": round(best.wind_kn),
                    "wind_from": compass(best.wind_from),
                    "wind": wind_relation(spot, best.wind_from),
                    "tide": _tide_trend(hours, best),
                    "rating": rate(spot, best),
                }
            )
    return out


async def fetch_hours(
    http: httpx.AsyncClient, spot: Spot, *, days: int, timezone: str
) -> list[Hour]:
    """Hourly swell, wind and sea level for a spot; hours with gaps are skipped."""
    common: dict[str, str | float | int] = {
        "latitude": spot.latitude,
        "longitude": spot.longitude,
        "timezone": timezone,
        "forecast_days": days,
    }
    marine_vars = "swell_wave_height,swell_wave_period,swell_wave_direction,sea_level_height_msl"
    try:
        marine = await http.get(MARINE_URL, params={**common, "hourly": marine_vars})
        weather = await http.get(
            WEATHER_URL,
            params={
                **common,
                "hourly": "wind_speed_10m,wind_direction_10m",
                "wind_speed_unit": "kn",
            },
        )
        marine.raise_for_status()
        weather.raise_for_status()
    except httpx.HTTPError as err:
        raise ForecastError(f"Open-Meteo is unavailable ({type(err).__name__})") from err
    m, w = marine.json()["hourly"], weather.json()["hourly"]
    wind = {
        at: (speed, direction)
        for at, speed, direction in zip(
            w["time"], w["wind_speed_10m"], w["wind_direction_10m"], strict=True
        )
    }
    hours = []
    for i, at in enumerate(m["time"]):
        swell = m["swell_wave_height"][i]
        period = m["swell_wave_period"][i]
        direction = m["swell_wave_direction"][i]
        speed, wind_from = wind.get(at, (None, None))
        if swell is None or period is None or direction is None:
            continue
        if speed is None or wind_from is None:
            continue
        hours.append(
            Hour(
                time=datetime.fromisoformat(at),
                swell_m=swell,
                period_s=period,
                swell_from=direction,
                wind_kn=speed,
                wind_from=wind_from,
                sea_level_m=m["sea_level_height_msl"][i],
            )
        )
    return hours
