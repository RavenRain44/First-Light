"""Iowa Environmental Mesonet ASOS observations (obhistory + currents).

obhistory serves one *local* day per call and works for any past date, so it
backs both the live "past 12h" chart and replay. Only observations at or
before ``as_of`` are returned, so replay never sees the future.
"""
from __future__ import annotations

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


async def fetch_obhistory(station: str, start: datetime, end: datetime, tz: str, urls: list[str] | None = None):
    """All observations in [start, end] (UTC), fetching each local day once."""
    zone = ZoneInfo(tz)
    d = start.astimezone(zone).date()
    last = end.astimezone(zone).date()
    rows, fetched = [], []
    today_local = datetime.now(zone).date()
    while d <= last:
        url = f"{IEM}/obhistory.json?network=IA_ASOS&station={station}&date={d.isoformat()}&full=true"
        if urls is not None:
            urls.append(url)
        r = await cache.get_json(url, historical=d < today_local)
        fetched.append(r.fetched_at)
        rows += r.data.get("data", [])
        d += timedelta(days=1)
    rows = [x for x in rows if x.get("utc_valid") and start <= _t(x["utc_valid"]) <= end]
    rows.sort(key=lambda x: x["utc_valid"])
    return rows, max(fetched) if fetched else None


def obs_series(rows: list[dict]) -> dict[str, list[tuple[datetime, float]]]:
    gust = [(_t(x["utc_valid"]), max(filter(None, [_kt(x.get("gust")), _kt(x.get("peak_wind_gust"))]), default=None)) for x in rows]
    wind = [(_t(x["utc_valid"]), _kt(x.get("sknt"))) for x in rows]
    temp = [(_t(x["utc_valid"]), x.get("tmpf")) for x in rows]
    feel = [(_t(x["utc_valid"]), x.get("feel")) for x in rows]
    vsby = [(_t(x["utc_valid"]), x.get("vsby")) for x in rows]
    p01 = [(_t(x["utc_valid"]), x.get("p01i")) for x in rows]
    fz = [(_t(x["utc_valid"]), 1.0 if any(c in (x.get("wxcodes") or "") for c in FREEZING_CODES) else 0.0) for x in rows]
    sn = [(_t(x["utc_valid"]), 1.0 if "SN" in (x.get("wxcodes") or "") else 0.0) for x in rows]
    return {
        "wind_gust_mph": hourly_reduce(gust, "max"),
        "wind_speed_mph": hourly_reduce(wind, "max"),
        "temp_f": hourly_reduce(temp, "last"),
        "apparent_temp_f": hourly_reduce(feel, "min"),
        "visibility_mi": hourly_reduce(vsby, "min"),
        "precip_in": hourly_reduce(p01, "max"),
        "freezing_precip": hourly_reduce(fz, "max"),
        "snow_obs": hourly_reduce(sn, "max"),
    }


UNITS = {"wind_gust_mph": "mph", "wind_speed_mph": "mph", "temp_f": "degF", "apparent_temp_f": "degF",
         "visibility_mi": "mi", "precip_in": "in", "freezing_precip": "flag", "snow_obs": "flag"}


class IEMObsAdapter(Adapter):
    name = "iem_obs"
    label = "IEM ASOS observations"
    supports_historical = True
    coverage = "IA"  # we only configure Iowa ASOS (network IA_ASOS)

    def __init__(self, hours_back: int = 12):
        self.hours_back = hours_back

    async def fetch(self, facility: Facility, as_of: datetime) -> list[NormalizedInput]:
        if not facility.asos_station:
            return []
        end = utc(as_of)
        start = end - timedelta(hours=self.hours_back)
        rows, fetched = await fetch_obhistory(facility.asos_station, start, end, facility.timezone, self._urls)
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
                note="hourly max gust/wind (knots converted to mph), last temp, min feels-like",
            ))
        if not is_historical(as_of):
            out += await self._currents(facility)
        return out

    async def _currents(self, facility: Facility) -> list[NormalizedInput]:
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
        out = []
        for key in ("ice_accretion_1hr", "ice_accretion_3hr", "ice_accretion_6hr"):
            out.append(NormalizedInput(
                id=f"obs.{key}_in", kind="scalar", role="observation", metric=f"{key}_in", unit="in",
                value=x.get(key), source=f"IEM currents {facility.asos_station}",
                source_url=url, fetched_at=r.fetched_at, source_time=valid,
                note=None if x.get(key) is not None else "not reported by the station this hour",
            ))
        return out
