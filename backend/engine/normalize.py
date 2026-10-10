"""Unit conversion, NWS gridpoint interval expansion and hourly aggregation."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

KMH_TO_MPH = 0.621371
MS_TO_MPH = 2.236936
KT_TO_MPH = 1.150779
MM_TO_IN = 1 / 25.4

# NWS gridpoint elements that are amounts accumulated over the interval (split
# evenly across its hours) vs. states that hold for every hour of the interval.
ACCUMULATIONS = {"iceAccumulation", "snowfallAmount", "quantitativePrecipitation"}


def c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


def convert(value: float | None, uom: str | None) -> tuple[float | None, str]:
    """Convert an NWS wmoUnit value to US customary units. Returns (value, unit)."""
    if value is None:
        return None, _target_unit(uom)
    u = (uom or "").replace("wmoUnit:", "").replace("unit:", "")
    if u == "km_h-1":
        return value * KMH_TO_MPH, "mph"
    if u == "m_s-1":
        return value * MS_TO_MPH, "mph"
    if u in ("kt", "knots"):
        return value * KT_TO_MPH, "mph"
    if u == "degC":
        return c_to_f(value), "degF"
    if u == "degF":
        return value, "degF"
    if u == "mm":
        return value * MM_TO_IN, "in"
    if u == "m":
        return value * 39.3701, "in"
    if u == "percent":
        return value, "%"
    return value, u or ""


def _target_unit(uom: str | None) -> str:
    return convert(0.0, uom)[1] if uom else ""


_DUR = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$")


def parse_duration(text: str) -> timedelta:
    """Parse the ISO-8601 durations NWS uses (PT3H, P2D, P1DT6H, PT30M)."""
    m = _DUR.match(text)
    if not m or not any(m.groups()):
        raise ValueError(f"unsupported ISO-8601 duration: {text!r}")
    d, h, mins = (int(g) if g else 0 for g in m.groups())
    return timedelta(days=d, hours=h, minutes=mins)


def parse_valid_time(valid_time: str) -> tuple[datetime, timedelta]:
    """'2026-10-10T12:00:00+00:00/PT3H' -> (start UTC, duration)."""
    start_s, dur_s = valid_time.split("/")
    start = datetime.fromisoformat(start_s.replace("Z", "+00:00")).astimezone(timezone.utc)
    return start, parse_duration(dur_s)


def expand_grid_element(element: str, values: list[dict], uom: str | None) -> list[tuple[datetime, float | None]]:
    """Expand interval values into hourly points in US units.

    State elements (wind, temperature, PoP) repeat for each hour of the interval;
    accumulations (ice, snow, QPF) are divided evenly across the hours so that
    sums over any window stay correct.
    """
    out: list[tuple[datetime, float | None]] = []
    accum = element in ACCUMULATIONS
    for item in values:
        start, dur = parse_valid_time(item["validTime"])
        hours = max(1, int(dur.total_seconds() // 3600))
        v, _ = convert(item.get("value"), uom)
        if accum and v is not None:
            v = v / hours
        for i in range(hours):
            out.append((start + timedelta(hours=i), v))
    return out


def hourly_reduce(points: Iterable[tuple[datetime, float | None]], how: str = "max") -> list[tuple[datetime, float]]:
    """Group points by UTC hour and reduce with max/min/sum/last (Nones dropped)."""
    buckets: dict[datetime, list[float]] = defaultdict(list)
    for t, v in points:
        if v is None:
            continue
        buckets[t.replace(minute=0, second=0, microsecond=0)].append(v)
    fn = {"max": max, "min": min, "sum": sum, "last": lambda xs: xs[-1], "mean": lambda xs: sum(xs) / len(xs)}[how]
    return sorted((t, fn(vs)) for t, vs in buckets.items())


def window(points: list[tuple[datetime, float]], start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    return [(t, v) for t, v in points if start <= t < end]
