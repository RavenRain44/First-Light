"""Turn normalized inputs into the named signals that threshold rules test.

A signal carries its value, unit, the time of its peak, the input ids that
produced it and (for forecasts) the hourly series, so a rule can work out
*when* its threshold is exceeded, which drives the timing-based posture.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

from pydantic import BaseModel

from adapters.base import NormalizedInput, utc

FORECAST_HOURS = 24
OBS_LOOKBACK = timedelta(hours=3)
OBS_PERSIST = timedelta(hours=3)  # an observed condition is assumed to persist this long


class Signal(BaseModel):
    id: str
    label: str
    value: float | None
    unit: str
    role: str  # forecast | observation | outlook
    peak_time: datetime | None = None
    hourly: list[tuple[datetime, float]] | None = None
    accumulation: bool = False
    window: tuple[datetime, datetime] | None = None
    input_ids: list[str] = []
    available: bool = True
    detail: str | None = None
    data: dict[str, Any] | None = None


class Context(BaseModel):
    as_of: datetime
    horizon_end: datetime  # forecast/alert look-ahead: through the decision day, at least 24 h
    signals: dict[str, Signal]
    alerts: list[dict]
    alert_input_ids: dict[str, str]  # alert id -> input id


def _series(inputs: dict[str, NormalizedInput], key: str) -> list[tuple[datetime, float]]:
    inp = inputs.get(key)
    if not inp or not inp.series:
        return []
    return [(utc(p.t), p.v) for p in inp.series if p.v is not None]


def wind_chill_f(t_f: float, v_mph: float) -> float:
    """NWS wind chill formula (valid for T <= 50 F and V >= 3 mph; otherwise returns T)."""
    if t_f > 50 or v_mph < 3:
        return t_f
    return 35.74 + 0.6215 * t_f - 35.75 * v_mph ** 0.16 + 0.4275 * t_f * v_mph ** 0.16


def _missing(sid: str, label: str, unit: str, role: str, why: str) -> Signal:
    return Signal(id=sid, label=label, value=None, unit=unit, role=role, available=False, detail=why)


def extract(inputs_list: list[NormalizedInput], as_of: datetime, employees: list[dict] | None = None,
            horizon_end: datetime | None = None, tz_name: str = "America/Chicago") -> Context:
    as_of = utc(as_of)
    inputs = {i.id: i for i in inputs_list}
    h0 = as_of.replace(minute=0, second=0, microsecond=0)
    h_end = max(utc(horizon_end), as_of + timedelta(hours=FORECAST_HOURS)) if horizon_end else as_of + timedelta(hours=FORECAST_HOURS)
    sig: dict[str, Signal] = {}

    def fwin(key):
        return [(t, v) for t, v in _series(inputs, key) if h0 <= t < h_end]

    # ---- forecast accumulations
    for metric, sid, label in (("ice_in", "fcst_ice_24h_in", "Forecast ice accumulation (24 h)"),
                               ("snow_in", "fcst_snow_24h_in", "Forecast snowfall (24 h)")):
        pts = fwin(f"fcst.{metric}")
        if not pts:
            sig[sid] = _missing(sid, label, "in", "forecast", "no forecast series available")
            continue
        peak = max(pts, key=lambda x: x[1])
        sig[sid] = Signal(id=sid, label=label, value=round(sum(v for _, v in pts), 3), unit="in", role="forecast",
                          peak_time=peak[0] if peak[1] > 0 else None, hourly=pts, accumulation=True,
                          input_ids=[f"fcst.{metric}"])
    snow = fwin("fcst.snow_in")
    if snow:
        best, best_t, best_win = 0.0, None, None
        for i in range(len(snow)):
            win = [p for p in snow if snow[i][0] <= p[0] < snow[i][0] + timedelta(hours=12)]
            total = sum(v for _, v in win)
            if total > best:
                best, best_t, best_win = total, snow[i][0], win
        sig["fcst_snow_12h_in"] = Signal(
            id="fcst_snow_12h_in", label="Forecast snowfall, heaviest 12 h", value=round(best, 2), unit="in",
            role="forecast", peak_time=best_t, hourly=best_win or snow, accumulation=True, input_ids=["fcst.snow_in"])
    else:
        sig["fcst_snow_12h_in"] = _missing("fcst_snow_12h_in", "Forecast snowfall, heaviest 12 h", "in", "forecast",
                                           "no forecast series available")

    # ---- forecast maxima / minima
    for metric, sid, label in (("wind_gust_mph", "fcst_max_gust_24h_mph", "Forecast max wind gust (24 h)"),
                               ("wind_speed_mph", "fcst_max_sustained_24h_mph", "Forecast max sustained wind (24 h)")):
        pts = fwin(f"fcst.{metric}")
        if not pts:
            sig[sid] = _missing(sid, label, "mph", "forecast", "no forecast series available")
            continue
        peak = max(pts, key=lambda x: x[1])
        sig[sid] = Signal(id=sid, label=label, value=round(peak[1], 1), unit="mph", role="forecast",
                          peak_time=peak[0], hourly=pts, input_ids=[f"fcst.{metric}"])

    app = fwin("fcst.apparent_temp_f")
    app_ids = ["fcst.apparent_temp_f"]
    detail = None
    if not app:
        temps, winds = dict(fwin("fcst.temp_f")), dict(fwin("fcst.wind_speed_mph"))
        app = [(t, round(wind_chill_f(v, winds.get(t, 0.0)), 1)) for t, v in sorted(temps.items())]
        app_ids = ["fcst.temp_f", "fcst.wind_speed_mph"]
        detail = "computed from forecast temperature and wind with the NWS wind chill formula"
    if app:
        low = min(app, key=lambda x: x[1])
        sig["fcst_min_apparent_24h_f"] = Signal(
            id="fcst_min_apparent_24h_f", label="Forecast lowest feels-like temperature (24 h)", value=round(low[1], 1),
            unit="degF", role="forecast", peak_time=low[0], hourly=app, input_ids=app_ids, detail=detail)
    else:
        sig["fcst_min_apparent_24h_f"] = _missing("fcst_min_apparent_24h_f", "Forecast lowest feels-like temperature (24 h)",
                                                  "degF", "forecast", "no forecast temperature")

    # ---- observations (last 3 h; persistence window going forward)
    obs_win = (as_of - timedelta(hours=1), as_of + OBS_PERSIST)

    def owin(key):
        return [(t, v) for t, v in _series(inputs, key) if as_of - OBS_LOOKBACK <= t <= as_of]

    fz = owin("obs.freezing_precip")
    if "obs.freezing_precip" in inputs:
        hours = [t for t, v in fz if v >= 1]
        sig["obs_freezing_precip_hours_3h"] = Signal(
            id="obs_freezing_precip_hours_3h", label="Observed freezing precip (hours of last 3)", value=float(len(hours)),
            unit="hours", role="observation", peak_time=max(hours) if hours else None, window=obs_win,
            input_ids=["obs.freezing_precip"])
    else:
        sig["obs_freezing_precip_hours_3h"] = _missing("obs_freezing_precip_hours_3h", "Observed freezing precip (hours of last 3)",
                                                       "hours", "observation", "no ASOS observations")
    acc = inputs.get("obs.ice_accretion_3hr_in")
    if acc is not None and acc.value is not None:
        sig["obs_ice_accretion_3h_in"] = Signal(
            id="obs_ice_accretion_3h_in", label="Measured ice accretion (3 h)", value=float(acc.value), unit="in",
            role="observation", peak_time=acc.source_time, window=obs_win, input_ids=[acc.id])
    else:
        sig["obs_ice_accretion_3h_in"] = _missing("obs_ice_accretion_3h_in", "Measured ice accretion (3 h)", "in",
                                                  "observation", "icing sensor value not reported (live only)")
    og = owin("obs.wind_gust_mph")
    if og:
        pk = max(og, key=lambda x: x[1])
        sig["obs_max_gust_3h_mph"] = Signal(
            id="obs_max_gust_3h_mph", label="Observed max gust (last 3 h)", value=round(pk[1], 1), unit="mph",
            role="observation", peak_time=pk[0], window=obs_win, input_ids=["obs.wind_gust_mph"])
    else:
        sig["obs_max_gust_3h_mph"] = _missing("obs_max_gust_3h_mph", "Observed max gust (last 3 h)", "mph", "observation",
                                              "no gust observations in the last 3 h")

    # combined gust for the destructive-wind rule
    cands = [s for s in (sig.get("fcst_max_gust_24h_mph"), sig.get("obs_max_gust_3h_mph")) if s and s.available]
    if cands:
        best = max(cands, key=lambda s: s.value)
        sig["max_gust_mph"] = best.model_copy(update={"id": "max_gust_mph", "label": f"Max gust ({best.label.lower()})"})
    else:
        sig["max_gust_mph"] = _missing("max_gust_mph", "Max gust (forecast or observed)", "mph", "observation", "no wind data")

    # ---- roads / RWIS
    roads = [i for i in inputs_list if i.kind == "road" and i.value is not None]
    if roads:
        worst = max(roads, key=lambda i: i.value)
        commuters: dict[str, int] = {}
        for e in employees or []:
            commuters[e.get("commute_corridor", "")] = commuters.get(e.get("commute_corridor", ""), 0) + 1
        bad = [r.data["corridor"] for r in roads if r.value >= 3]
        sig["road_worst_rank"] = Signal(
            id="road_worst_rank", label="Worst Iowa DOT condition on a commute corridor", value=worst.value, unit="rank",
            role="observation", peak_time=worst.source_time, window=obs_win, input_ids=[r.id for r in roads],
            detail=f"{worst.data['label']} on {worst.data['name']}",
            data={"corridor": worst.data["corridor"], "label": worst.data["label"],
                  "commuters_on_covered_corridors": sum(commuters.get(c, 0) for c in bad)})
    else:
        sig["road_worst_rank"] = _missing("road_worst_rank", "Worst Iowa DOT condition on a commute corridor", "rank",
                                          "observation", "no Iowa DOT road reports (out of season, out of Iowa, or unavailable)")
    rw = inputs.get("rwis.ice_condition_sensors")
    if rw is not None:
        sig["rwis_ice_sensors"] = Signal(id="rwis_ice_sensors", label="RWIS sensors reporting ice", value=float(rw.value),
                                         unit="sensors", role="observation", peak_time=rw.source_time, window=obs_win,
                                         input_ids=[rw.id])
    else:
        sig["rwis_ice_sensors"] = _missing("rwis_ice_sensors", "RWIS sensors reporting ice", "sensors", "observation",
                                           "no RWIS data")

    # ---- SPC outlook
    spc = inputs.get("spc.day1_category")
    if spc is not None:
        d = spc.data or {}
        start = datetime.fromisoformat(d["issue"].replace("Z", "+00:00")) if d.get("issue") else as_of
        end = datetime.fromisoformat(d["expire"].replace("Z", "+00:00")) if d.get("expire") else as_of + timedelta(hours=24)
        # The outlook covers 12Z-12Z but says nothing about timing. Policy: time it to the local
        # afternoon/evening convective peak (12:00-21:00) of the outlook day.
        day = (utc(start) + timedelta(hours=12)).astimezone(ZoneInfo(tz_name)).date()
        w0 = max(utc(start), datetime.combine(day, time(12), ZoneInfo(tz_name)).astimezone(timezone.utc))
        w1 = min(utc(end), datetime.combine(day, time(21), ZoneInfo(tz_name)).astimezone(timezone.utc))
        sig["spc_day1_rank"] = Signal(id="spc_day1_rank", label="SPC day-1 convective outlook", value=float(d.get("rank", -1)),
                                      unit="category", role="outlook", peak_time=w0, window=(w0, w1),
                                      input_ids=[spc.id], detail=str(spc.value))
    else:
        sig["spc_day1_rank"] = _missing("spc_day1_rank", "SPC day-1 convective outlook", "category", "outlook", "no SPC outlook")

    alerts = [i.data for i in inputs_list if i.kind == "alert" and i.data]
    return Context(as_of=as_of, horizon_end=h_end, signals=sig, alerts=alerts,
                   alert_input_ids={i.data["id"]: i.id for i in inputs_list if i.kind == "alert" and i.data})


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
