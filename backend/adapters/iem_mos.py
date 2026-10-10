"""Archived National Blend of Models short-range text (NBS) forecasts via IEM.

Replay uses the newest NBS run that was already published at ``as_of`` so the
forecast panel shows what was predicted then, not hindsight. Element units per
the NBM text bulletin key (vlab.noaa.gov/web/mdl/nbm-textcard-v4.2):
GST/WSP knots, TMP degF, Q06 1/100 in, S06 1/10 in, I06 1/100 in, P06 percent.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from adapters import cache
from adapters.base import Adapter, Facility, NormalizedInput, Point, is_historical, iso_z, utc
from engine.normalize import KT_TO_MPH

IEM = "https://mesonet.agron.iastate.edu/api/1"
NBS_CYCLES = (1, 7, 13, 19)  # UTC hours NBS text runs are issued
AVAILABILITY_LAG = timedelta(hours=2)  # a run is not usable until ~1-2h after its nominal time


def runtime_candidates(as_of: datetime, n: int = 4) -> list[datetime]:
    t = utc(as_of) - AVAILABILITY_LAG
    out = []
    day = t.replace(hour=0, minute=0, second=0, microsecond=0)
    while len(out) < n:
        for h in sorted(NBS_CYCLES, reverse=True):
            cand = day.replace(hour=h)
            if cand <= t and cand not in out:
                out.append(cand)
                if len(out) == n:
                    break
        day -= timedelta(days=1)
    return out


def _ft(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "")).replace(tzinfo=timezone.utc)


def mos_to_hourly(rows: list[dict]) -> dict[str, list[tuple[datetime, float | None]]]:
    """3-hourly states held for the 3 hours they represent; 6-h amounts spread over the 6 hours ending at ftime."""
    out: dict[str, dict[datetime, float]] = {k: {} for k in
                                             ("wind_gust_mph", "wind_speed_mph", "temp_f", "ice_in", "snow_in", "qpf_in", "pop_pct")}
    for x in rows:
        ft = _ft(x["ftime_utc"])
        for key, metric, f in (("gst", "wind_gust_mph", KT_TO_MPH), ("wsp", "wind_speed_mph", KT_TO_MPH), ("tmp", "temp_f", 1.0)):
            if x.get(key) is not None:
                for h in (-1, 0, 1):
                    out[metric][ft + timedelta(hours=h)] = round(x[key] * f, 1)
        for key, metric, scale in (("i06", "ice_in", 0.01), ("s06", "snow_in", 0.1), ("q06", "qpf_in", 0.01)):
            if x.get(key) is not None:
                for h in range(6):
                    out[metric][ft - timedelta(hours=h + 1)] = round(x[key] * scale / 6, 4)
        if x.get("p06") is not None:
            for h in range(6):
                out["pop_pct"][ft - timedelta(hours=h + 1)] = x["p06"]
    return {k: sorted(v.items()) for k, v in out.items()}


class IEMMOSAdapter(Adapter):
    """Forecast source for replay (archived NBS). Live uses NWS gridpoints instead."""

    name = "iem_mos"
    label = "Archived NBM forecast (IEM MOS/NBS)"
    supports_historical = True
    historical_only = True
    coverage = "US"

    async def fetch(self, facility: Facility, as_of: datetime) -> list[NormalizedInput]:
        if not facility.mos_station:
            return []
        # NBS's first projection is 6 h after issue, so the newest run leaves a gap right after
        # as_of. Fill it from the previous run; newer values win wherever both exist.
        runs = []
        for rt in runtime_candidates(as_of, n=5):
            url = f"{IEM}/mos.json?station={facility.mos_station}&model=NBS&runtime={iso_z(rt)}"
            self._urls.append(url)
            try:
                r = await cache.get_json(url, historical=is_historical(rt))
            except cache.SourceUnavailable:
                continue  # IEM returns 422 when a run is missing; try the previous cycle
            if r.data.get("data"):
                runs.append((rt, url, r))
            if len(runs) == 2:
                break
        if not runs:
            return []
        runtime, url, r = runs[0]
        merged: dict[str, dict] = {}
        for _, _, rr in reversed(runs):
            for row in rr.data["data"]:
                merged[row["ftime_utc"]] = row
        rows = sorted(merged.values(), key=lambda x: x["ftime_utc"])
        start = utc(as_of).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        end = start + timedelta(hours=74)
        out = []
        units = {"wind_gust_mph": "mph", "wind_speed_mph": "mph", "temp_f": "degF", "ice_in": "in",
                 "snow_in": "in", "qpf_in": "in", "pop_pct": "%"}
        for metric, pts in mos_to_hourly(rows).items():
            pts = [(t, v) for t, v in pts if start <= t < end]
            if not pts:
                continue
            out.append(NormalizedInput(
                id=f"fcst.{metric}", kind="series", role="forecast", metric=metric, unit=units[metric],
                series=[Point(t=t, v=v) for t, v in pts],
                source=f"NBM NBS {facility.mos_station} run {iso_z(runtime)}" + (f" + {iso_z(runs[1][0])}" if len(runs) > 1 else "") + " (IEM archive)", source_url=url,
                fetched_at=r.fetched_at, source_time=runtime,
                note="forecast as issued before as_of; 3-hourly values held, 6-h amounts spread hourly",
            ))
        return out
