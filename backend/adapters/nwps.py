"""Official NOAA NWPS gauge forecasts; gauge flooding is not site inundation.

The current feed has rolling observations and the latest forecast, not a verified
original forecast archive for old hurricanes. It is consequently live-only.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from adapters import cache
from adapters.base import Adapter, Facility, NormalizedInput, Point, utc
from adapters.ncdot import number

API = "https://api.water.noaa.gov/nwps/v1/gauges"
GAUGE_ID = re.compile(r"^[A-Z0-9]{3,8}$")


def dt(value) -> datetime | None:
    try:
        return utc(datetime.fromisoformat(value.replace("Z", "+00:00"))) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def gauge_datum(meta: dict) -> str | None:
    # This API identifies tidal datums in the gauge name (verified WLON7:
    # Cape Fear River at Wilmington (IN MLLW)). Never infer one from coordinates.
    match = re.search(r"\(IN (MLLW|MHHW|NAVD88|NGVD29)\)", meta.get("name", ""), re.I)
    return match.group(1).upper() if match else None


def normalize_gauge(meta: dict, hydro: dict, gauge: dict, as_of: datetime, fetched_at: datetime,
                    url: str) -> list[NormalizedInput]:
    station = str(meta.get("lid", "")).upper()
    if station != str(gauge.get("id", "")).upper():
        raise cache.SourceUnavailable("NWPS returned a different gauge than requested.")
    datum = gauge_datum(meta)
    if not datum:
        raise cache.SourceUnavailable("Gauge datum is not identified by the NWPS source; numeric water-level comparisons are unavailable.")
    if gauge.get("datum") and str(gauge["datum"]).upper() != datum:
        raise cache.SourceUnavailable("Configured gauge datum differs from the NWPS source datum.")
    flood = meta.get("flood") or {}
    thresholds = {k: number((flood.get("categories", {}).get(k) or {}).get("stage")) for k in ("action", "minor", "moderate", "major")}
    thresholds = {k: v for k, v in thresholds.items() if v is not None and v > -999}
    if flood.get("stageUnits") != "ft":
        thresholds = {}  # Numeric thresholds cannot be used against different units.
    out, now = [], utc(as_of)
    for role, field in (("observation", "observed"), ("forecast", "forecast")):
        block = hydro.get(field) or {}
        issue = dt(block.get("issuedTime"))
        if block.get("primaryUnits") != "ft" or not issue or issue > now:
            continue
        values, generated = {}, {}
        for row in block.get("data", []):
            valid, published = dt(row.get("validTime")), dt(row.get("generatedTime"))
            v = number(row.get("primary"))
            if valid is None or published is None or published > now or v is None or v <= -999:
                continue
            if role == "observation" and not now-timedelta(hours=12) <= valid <= now:
                continue
            if role == "forecast" and not now-timedelta(hours=1) <= valid <= now+timedelta(hours=72):
                continue
            values[valid] = v
            generated[valid.isoformat()] = published.isoformat()
        if not values:
            continue
        data = {"station_id": station, "gauge_id": station, "station_name": meta.get("name"),
                "datum": datum, "flood_stage_ft": thresholds.get("minor"), "flood_thresholds_ft": thresholds,
                "generated_times": generated, "issued_time": issue.isoformat(),
                "latitude": meta.get("latitude"), "longitude": meta.get("longitude"),
                "facility_inundation": False, "scope": "Regional tidal gauge context; this does not forecast water depth at the facility.",
                "kind": gauge.get("kind", "tidal_river")}
        out.append(NormalizedInput(
            id=f"water.{station}.{field}", kind="series", role=role, metric="water_level_ft", unit="ft",
            series=[Point(t=t, v=round(v, 3)) for t, v in sorted(values.items())], data=data,
            source=f"NOAA NWPS {station}", source_url=url, fetched_at=fetched_at,
            source_time=max(values) if role == "observation" else issue,
            note="Feet above the gauge's MLLW datum. Tide/river level includes multiple influences; it is not storm surge alone or facility inundation." if datum == "MLLW" else f"Water level in feet above {datum}; regional gauge context, not facility inundation.",
        ))
    return out


class NWPSWaterAdapter(Adapter):
    name = "nwps_water"
    label = "NOAA NWPS coastal water level"
    supports_historical = False

    def __init__(self, allow_demo_bypass: bool = False):
        self.allow_demo_bypass = allow_demo_bypass

    async def fetch(self, facility: Facility, as_of: datetime) -> list[NormalizedInput]:
        out = []
        for gauge in getattr(facility, "water_gauges", []) or []:
            station = str(gauge.get("id", "")).upper()
            if not GAUGE_ID.fullmatch(station):
                raise cache.SourceUnavailable("Invalid configured NWPS gauge identifier.")
            meta_url, hydro_url = f"{API}/{station.lower()}", f"{API}/{station.lower()}/stageflow"
            self._urls.extend((meta_url, hydro_url))
            meta = await cache.get_json(meta_url, ttl=3600, allow_demo_bypass=self.allow_demo_bypass)
            hydro = await cache.get_json(hydro_url, ttl=300, allow_demo_bypass=self.allow_demo_bypass)
            out.extend(normalize_gauge(meta.data, hydro.data, gauge, as_of, hydro.fetched_at, hydro_url))
        return out
