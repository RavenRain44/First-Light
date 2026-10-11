"""Iowa Environmental Mesonet ASOS observations (obhistory + currents).

obhistory serves one *local* day per call and works for any past date, so it
backs both the live "past 12h" chart and replay. Only observations at or
before ``as_of`` are returned, so replay never sees the future.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from adapters import cache
from adapters.base import Adapter, Facility, NormalizedInput, Point, is_historical, utc
from engine.normalize import KT_TO_MPH, hourly_reduce

IEM = "https://mesonet.agron.iastate.edu/api/1"

FREEZING_CODES = ("FZRA", "FZDZ", "PL")  # freezing rain, freezing drizzle, ice pellets


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _kt(v):
    return None if v is None else v * KT_TO_MPH


async def fetch_obhistory(station: str, start: datetime, end: datetime, tz: str, urls: list[str] | None = None,
                          network: str = "IA_ASOS"):
    """All observations in [start, end] (UTC), fetching each local day once."""
    zone = ZoneInfo(tz)
    d = start.astimezone(zone).date()
    last = end.astimezone(zone).date()
    rows, fetched = [], []
    today_local = datetime.now(zone).date()
    while d <= last:
        url = f"{IEM}/obhistory.json?network={network}&station={station}&date={d.isoformat()}&full=true"
        if urls is not None:
            urls.append(url)
        r = await cache.get_json(url, historical=d < today_local)
        fetched.append(r.fetched_at)
        rows += r.data.get("data", [])
        d += timedelta(days=1)
    rows = [x for x in rows if x.get("utc_valid") and start <= _t(x["utc_valid"]) <= end]
    rows.sort(key=lambda x: x["utc_valid"])
    return rows, max(fetched) if fetched else None


_TGROUP = re.compile(r"(?<!\S)T([01])(\d{3})([01])(\d{3})(?!\S)")


def precise_temp_f(row: dict) -> float | None:
    """Temperature from the METAR T-group (tenths of a degree C) when present, else IEM's tmpf."""
    m = _TGROUP.search(row.get("raw") or "")
    if m:
        c = int(m.group(2)) / 10 * (-1 if m.group(1) == "1" else 1)
        return round(c * 9 / 5 + 32, 1)
    return row.get("tmpf")


def is_routine(row: dict) -> bool:
    """The routine hourly METAR (the report weather.gov lists) carries sea-level pressure (SLP) and a temperature."""
    raw = row.get("raw") or ""
    return " SLP" in raw or (row.get("tmpf") is not None and " AO2" in raw)


def obs_series(rows: list[dict]) -> dict[str, list[tuple[datetime, float]]]:
    """Hourly observation series.

    Temperature, wind, gust, feels-like and precipitation come from each hour's routine
    hourly METAR, the same report weather.gov shows, so values match the NWS station history.
    ``peak_gust_mph`` is the highest gust in any report that hour (5-minute obs and the
    METAR peak-wind remark); it feeds the wind thresholds, conservatively. Freezing-rain
    and snow flags are set if any report in the hour had them.
    """
    by_hour: dict[datetime, list[dict]] = {}
    for x in rows:
        by_hour.setdefault(_t(x["utc_valid"]).replace(minute=0, second=0, microsecond=0), []).append(x)
    out: dict[str, list[tuple[datetime, float]]] = {k: [] for k in UNITS}
    for hr in sorted(by_hour):
        obs = by_hour[hr]
        routine = [x for x in obs if is_routine(x)]
        r = routine[-1] if routine else next((x for x in reversed(obs) if x.get("tmpf") is not None), obs[-1])
        t = _t(r["utc_valid"]).replace(minute=0, second=0, microsecond=0)
        vals = {
            "temp_f": precise_temp_f(r),
            "apparent_temp_f": r.get("feel"),
            "wind_speed_mph": _kt(r.get("sknt")),
            "wind_gust_mph": _kt(r.get("gust")),
            "visibility_mi": r.get("vsby"),
            "precip_in": r.get("p01i"),
            "peak_gust_mph": max(filter(None, [_kt(x.get("gust")) for x in obs] + [_kt(x.get("peak_wind_gust")) for x in obs]), default=None),
            "freezing_precip": 1.0 if any(any(c in (x.get("wxcodes") or "") for c in FREEZING_CODES) for x in obs) else 0.0,
            "snow_obs": 1.0 if any("SN" in (x.get("wxcodes") or "") for x in obs) else 0.0,
        }
        for k, v in vals.items():
            if v is not None:
                out[k].append((t, v))
    return out


UNITS = {"wind_gust_mph": "mph", "peak_gust_mph": "mph", "wind_speed_mph": "mph", "temp_f": "degF",
         "apparent_temp_f": "degF", "visibility_mi": "mi", "precip_in": "in", "freezing_precip": "flag", "snow_obs": "flag"}


class IEMObsAdapter(Adapter):
    name = "iem_obs"
    label = "IEM ASOS observations"
    supports_historical = True
    coverage = "US"

    def __init__(self, hours_back: int = 12):
        self.hours_back = hours_back
        self._availability_lag = timedelta()
        self._nc_replay = False

    async def run(self, facility: Facility, as_of: datetime, mode: str):
        # New historical facilities use the same conservative latency assumption
        # as station-year replay. Original receipt times are not archived.
        self._nc_replay = facility.state == "NC" and mode != "live"
        self._availability_lag = timedelta(minutes=15) if self._nc_replay else timedelta()
        return await super().run(facility, as_of, mode)

    async def fetch(self, facility: Facility, as_of: datetime) -> list[NormalizedInput]:
        if not facility.asos_station:
            return []
        end = utc(as_of) - self._availability_lag
        start = end - timedelta(hours=self.hours_back)
        network = (getattr(facility, "provider_settings", {}) or {}).get("asos_network", f"{facility.state}_ASOS")
        rows, fetched = await fetch_obhistory(facility.asos_station, start, end, facility.timezone, self._urls,
                                             network=network)
        if not rows:
            return []
        latest = _t(rows[-1]["utc_valid"])
        out = []
        url = self._urls[-1]
        for metric, pts in obs_series(rows).items():
            out.append(NormalizedInput(
                id=f"obs.{metric}", kind="series", role="observation", metric=metric, unit=UNITS[metric],
                series=[Point(t=t, v=round(v, 2)) for t, v in pts],
                source=f"IEM ASOS {facility.asos_station} (obhistory)", source_url=url,
                fetched_at=fetched, source_time=latest,
                note=("highest gust in any report during the hour (5-minute obs + peak-wind remark)" if metric == "peak_gust_mph"
                      else "from the routine hourly METAR, as listed on weather.gov (knots converted to mph)")
                     + ("; replay assumes 15-minute availability latency; original receipt times are not archived" if self._availability_lag else ""),
            ))
        if not is_historical(as_of) and not self._nc_replay:
            out += await self._currents(facility, as_of)
        return out

    async def _currents(self, facility: Facility, as_of: datetime | None = None) -> list[NormalizedInput]:
        url = f"{IEM}/currents.json?station={facility.asos_station}"
        self._urls.append(url)
        try:
            r = await cache.get_json(url)
        except cache.SourceUnavailable:
            return []
        rows = [x for x in r.data.get("data", []) if x.get("network", "").endswith("ASOS")] or r.data.get("data", [])
        if not rows:
            return []
        x = rows[0]
        valid = _t(x["utc_valid"])
        if as_of is not None and valid > utc(as_of) - self._availability_lag:
            return []
        out = []
        for key in ("ice_accretion_1hr", "ice_accretion_3hr", "ice_accretion_6hr"):
            out.append(NormalizedInput(
                id=f"obs.{key}_in", kind="scalar", role="observation", metric=f"{key}_in", unit="in",
                value=x.get(key), source=f"IEM currents {facility.asos_station}",
                source_url=url, fetched_at=r.fetched_at, source_time=valid,
                note=None if x.get(key) is not None else "not reported by the station this hour",
            ))
        return out
