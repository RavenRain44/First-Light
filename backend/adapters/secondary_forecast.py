"""Backup forecasts. Live forecasts are never substituted into historical replay.

GFS MOS units: https://vlab.noaa.gov/web/mdl/mav-card (TMP Fahrenheit,
WSP knots, P06 percent). Q06/SNW are categories, not accumulation amounts.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from urllib.parse import urlencode

from adapters import cache
from adapters.base import Adapter, Facility, NormalizedInput, Point, floor_hour, iso_z, utc
from adapters.iem_mos import AVAILABILITY_LAG, IEM
from engine.normalize import KT_TO_MPH


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


class OpenMeteoAdapter(Adapter):
    name = "open_meteo"
    label = "Open-Meteo backup forecast"
    # Deliberately no archive support: today's forecast is not historical evidence.
    supports_historical = False

    def __init__(self, allow_demo_bypass=False):
        self.allow_demo_bypass = allow_demo_bypass

    async def fetch(self, facility: Facility, as_of: datetime):
        fields = {
            "temperature_2m": ("temp_f", "degF", {"°F": 1}),
            "apparent_temperature": ("apparent_temp_f", "degF", {"°F": 1}),
            "wind_speed_10m": ("wind_speed_mph", "mph", {"mp/h": 1, "mph": 1}),
            "wind_gusts_10m": ("wind_gust_mph", "mph", {"mp/h": 1, "mph": 1}),
            "precipitation": ("qpf_in", "in", {"inch": 1, "in": 1, "mm": 1 / 25.4}),
            "snowfall": ("snow_in", "in", {"inch": 1, "in": 1, "cm": 1 / 2.54}),
            "precipitation_probability": ("pop_pct", "%", {"%": 1}),
            "cloud_cover": ("sky_cover_pct", "%", {"%": 1}),
        }
        url = "https://api.open-meteo.com/v1/forecast?" + urlencode({
            "latitude": facility.lat, "longitude": facility.lon, "hourly": ",".join(fields),
            "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
            "precipitation_unit": "inch", "timezone": "UTC", "forecast_days": 3,
        })
        self._urls.append(url)
        response = await cache.get_json(url, allow_demo_bypass=self.allow_demo_bypass)
        units = response.data.get("hourly_units", {})
        hourly = response.data.get("hourly", {})
        if units.get("time") != "iso8601" or response.data.get("utc_offset_seconds") != 0:
            raise cache.SourceUnavailable("Backup forecast did not provide the requested UTC time axis")
        times = [utc(datetime.fromisoformat(t)) for t in hourly.get("time", [])]
        out = []
        for field, (metric, unit, scales) in fields.items():
            if units.get(field) not in scales:
                continue  # Unknown units remain missing, never guessed.
            values = hourly.get(field, [])
            if len(values) != len(times):
                continue
            pts = [Point(t=t, v=round(v * scales[units[field]], 4))
                   for t, raw in zip(times, values) if (v := number(raw)) is not None
                   and floor_hour(as_of) <= t <= utc(as_of) + timedelta(hours=72)]
            if pts:
                out.append(NormalizedInput(
                    id=f"fcst.{metric}", kind="series", role="context" if metric == "sky_cover_pct" else "forecast",
                    metric=metric, unit=unit, series=pts, source=self.label, source_url=url,
                    fetched_at=response.fetched_at, source_time=None,
                    data={"weather_fallback": True, "live_retrieval_only": True,
                          "limitations": ["Exact model issue time is unavailable; freshness uses the live retrieval time.",
                                           "Ice accumulation and official warnings are not supplied by this backup."]},
                    note="Secondary live model forecast; provisional. No historical or reanalysis substitution.",
                ))
        return out


def gfs_runtime_candidates(as_of: datetime, n=3):
    latest = floor_hour(utc(as_of) - AVAILABILITY_LAG)
    latest = latest.replace(hour=latest.hour // 6 * 6)
    return [latest - timedelta(hours=6 * j) for j in range(n)]


class ArchivedGFSAdapter(Adapter):
    name = "iem_gfs"
    label = "Archived GFS MOS backup forecast (IEM)"
    supports_historical = True
    historical_only = True

    async def fetch(self, facility: Facility, as_of: datetime):
        if not facility.mos_station:
            return []
        runs = []
        for runtime in gfs_runtime_candidates(as_of):
            if utc(as_of) - runtime > timedelta(hours=12):
                continue  # Do not fill near-term gaps using a stale prior run.
            url = f"{IEM}/mos.json?station={facility.mos_station}&model=GFS&runtime={iso_z(runtime)}"
            self._urls.append(url)
            try:
                response = await cache.get_json(url, historical=True)
            except cache.SourceUnavailable:
                continue
            # Validate actual run timestamps, not merely the requested URL.
            rows = [r for r in response.data.get("data", []) if r.get("model") == "GFS"
                    and r.get("station") == facility.mos_station and r.get("runtime_utc")
                    and utc(datetime.fromisoformat(r["runtime_utc"])) == runtime]
            if rows:
                runs.append((runtime, url, response, rows))
            if len(runs) == 2:
                break
        values = {k: {} for k in ("temp_f", "wind_speed_mph", "pop_pct")}
        for runtime, url, response, rows in reversed(runs):
            for row in rows:
                t = utc(datetime.fromisoformat(row["ftime_utc"]))
                for field, metric, scale, offsets in (
                    ("tmp", "temp_f", 1, (-1, 0, 1)),
                    ("wsp", "wind_speed_mph", KT_TO_MPH, (-1, 0, 1)),
                    ("p06", "pop_pct", 1, range(-6, 0)),
                ):
                    v = number(row.get(field))
                    if v is None or v >= 999 or (field != "tmp" and v < 0):
                        continue
                    for h in offsets:
                        when = t + timedelta(hours=h)
                        if floor_hour(as_of) - timedelta(hours=1) <= when <= utc(as_of) + timedelta(hours=72):
                            values[metric][when] = (v * scale, runtime, url, response.fetched_at)
        out = []
        for metric, pts in values.items():
            if not pts:
                continue
            source_time = max(p[1] for p in pts.values())
            url = next(p[2] for p in pts.values() if p[1] == source_time)
            out.append(NormalizedInput(
                id=f"fcst.{metric}", kind="series", role="forecast", metric=metric,
                unit={"temp_f": "degF", "wind_speed_mph": "mph", "pop_pct": "%"}[metric],
                series=[Point(t=t, v=round(p[0], 4)) for t, p in sorted(pts.items())],
                source=self.label, source_url=url, source_time=source_time,
                fetched_at=max(p[3] for p in pts.values()),
                data={"weather_fallback": True, "point_sources": {
                    iso_z(t): {"source_time": iso_z(p[1]), "source_url": p[2]} for t, p in pts.items()},
                    "limitations": ["Original GFS runs only; nominal run + 2-hour availability lag is an estimate.",
                                     "This backup provides temperature, sustained wind and precipitation probability; snow/ice amounts and gusts remain unknown."]},
                note="Original archived forecast, issued before the selected time. No categorical snow/QPF values treated as amounts.",
            ))
        return out
