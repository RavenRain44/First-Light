"""Evaluation pipeline: adapters -> signals -> rules -> hazards -> posture -> confidence.

``gather`` does the I/O; ``assess`` is pure, so tests and the backtest can feed
it saved inputs and get byte-identical results.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from adapters.base import Adapter, Facility, NormalizedInput, SourceStatus, utc
from adapters.iem_mos import IEMMOSAdapter
from adapters.iem_obs import IEMObsAdapter
from adapters.iem_roads import IEMRoadsAdapter, IEMRWISAdapter
from adapters.iem_vtec import IEMOutlookAdapter, IEMVTECAdapter
from adapters.nws import NWSAlertsAdapter, NWSGridAdapter, resolve_point
from adapters.secondary_forecast import ArchivedGFSAdapter, OpenMeteoAdapter
from adapters.ncdot import NCDOTRoadsAdapter
from adapters.nwps import NWPSWaterAdapter
from adapters.nws_hurricane import NWSHurricaneLocalAdapter
from engine import confidence as conf
from engine.counterfactual import Change, what_would_change
from engine.features import Context, Signal, extract
from engine.posture import PostureResult, decide, horizon_end
from engine.readiness import Readiness, assess_readiness
from engine.sufficiency import Sufficiency, assess_sufficiency
from engine.scoring import HazardResult, RuleResult, Thresholds, evaluate_rules, load_thresholds, score_hazards


class Assessment(BaseModel):
    as_of: datetime
    mode: str
    signals: dict[str, Signal]
    rules: list[RuleResult]
    hazards: dict[str, HazardResult]
    posture: PostureResult
    confidence: conf.Confidence
    changes: list[Change]
    readiness: Readiness
    sufficiency: Sufficiency
    watch_next_6h: list[str]
    features: dict[str, float]
    alerts: list[dict]


async def facility_ugcs(facility: Facility, allow_demo_bypass: bool = False) -> list[str]:
    """Forecast zone + county UGC codes, derived from NWS /points (not hardcoded)."""
    meta, _ = await resolve_point(facility.lat, facility.lon, allow_demo_bypass=allow_demo_bypass)
    return [meta["forecastZone"], meta["county"]]


async def adapters_for(facility: Facility, mode: str) -> list[Adapter]:
    if facility.state == "NC":
        demo_bypass = mode == "livecheck"
        common = [IEMObsAdapter(), NCDOTRoadsAdapter(allow_demo_bypass=demo_bypass),
                  NWPSWaterAdapter(allow_demo_bypass=demo_bypass),
                  NWSHurricaneLocalAdapter(allow_demo_bypass=demo_bypass), IEMOutlookAdapter()]
        if mode in ("live", "livecheck"):
            return [NWSAlertsAdapter(allow_demo_bypass=demo_bypass), NWSGridAdapter(allow_demo_bypass=demo_bypass)] + common
        try:
            ugcs = await facility_ugcs(facility)
        except Exception:  # noqa: BLE001 - original source unavailable; use verified site metadata
            ugcs = list(getattr(facility, "warning_ugcs", []))
        return [IEMVTECAdapter(ugcs), IEMMOSAdapter()] + common
    if mode == "livecheck":
        return [NWSAlertsAdapter(allow_demo_bypass=True), NWSGridAdapter(allow_demo_bypass=True),
                IEMObsAdapter(), IEMRoadsAdapter(), IEMRWISAdapter(), IEMOutlookAdapter()]
    common = [IEMObsAdapter(), IEMRoadsAdapter(), IEMRWISAdapter(), IEMOutlookAdapter()]
    if mode == "live":
        return [NWSAlertsAdapter(), NWSGridAdapter()] + common
    try:
        ugcs = await facility_ugcs(facility)
    except Exception:  # noqa: BLE001 - verified facility metadata, never another state's alert zone
        ugcs = list(getattr(facility, "warning_ugcs", []))
        if not ugcs:
            ugcs = ["IAZ048", "IAC169"] if facility.state == "IA" else (["NCZ107", "NCC129"] if facility.id == "NC-WILMINGTON-SC" else [])
    return [IEMVTECAdapter(ugcs), IEMMOSAdapter()] + common


async def gather(facility: Facility, as_of: datetime, mode: str) -> tuple[list[NormalizedInput], list[SourceStatus]]:
    adapters = await adapters_for(facility, mode)
    run_mode = "live" if mode in ("live", "livecheck") else "replay"
    results = await asyncio.gather(*(a.run(facility, as_of, run_mode) for a in adapters))
    inputs = [i for inp, _ in results for i in inp]
    statuses = [s for _, s in results]
    from engine.forecast_fallback import merge_backup, needs_backup
    if needs_backup(assess(inputs, statuses, facility, as_of, mode, employees=[]), inputs):
        backup = OpenMeteoAdapter(allow_demo_bypass=mode == "livecheck") if run_mode == "live" else ArchivedGFSAdapter()
        try:
            secondary, status = await asyncio.wait_for(backup.run(facility, as_of, run_mode), timeout=20)
        except TimeoutError:
            secondary, status = [], SourceStatus(adapter=backup.name, label=backup.label, status="unavailable",
                                                  detail="Backup forecast exceeded the 20-second request budget.")
        statuses.append(status)
        inputs = merge_backup(inputs, secondary, as_of, run_mode == "live")
    return inputs, statuses


def _watch(ctx: Context, rules: list[RuleResult], facility: Facility, sufficiency: Sufficiency | None = None) -> list[str]:
    tz = ZoneInfo(facility.timezone)
    now, end = ctx.as_of, ctx.as_of + timedelta(hours=6)
    fmt = lambda t: utc(t).astimezone(tz).strftime("%H:%M %Z")  # noqa: E731
    items = []
    for a in ctx.alerts:
        for key, verb in (("onset", "begins"), ("ends", "ends")):
            ts = a.get(key)
            if ts:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if now <= t <= end:
                    items.append(f"{a['event']} {verb} at {fmt(t)}")
    s = ctx.signals
    for sid, word in (("fcst_max_gust_24h_mph", "gust"), ("fcst_max_sustained_24h_mph", "sustained wind")):
        sig = s.get(sid)
        if sig and sig.available and sig.hourly:
            nxt = [(t, v) for t, v in sig.hourly if now <= t <= end]
            if nxt:
                t, v = max(nxt, key=lambda x: x[1])
                if v >= 25:
                    items.append(f"Forecast {word} peaks near {v:.0f} mph around {fmt(t)}")
    for sid, word in (("fcst_ice_24h_in", "ice"), ("fcst_snow_24h_in", "snow")):
        sig = s.get(sid)
        if sig and sig.available and sig.hourly:
            nxt = [(t, v) for t, v in sig.hourly if now <= t <= end and v > 0]
            if nxt:
                total = sum(v for _, v in nxt)
                if total >= 0.01:
                    items.append(f"Forecast {word} {total:.2f} in between {fmt(nxt[0][0])} and {fmt(nxt[-1][0] + timedelta(hours=1))}")
    road = s.get("road_worst_rank")
    if road and road.available and road.value and road.value >= 2:
        items.append(f"Roads: {road.detail}; re-check {'NCDOT' if facility.state == 'NC' else 'Iowa DOT'} reports before the next commute window")
    rain = s.get("fcst_rain_24h_in")
    if facility.state == "NC" and rain and rain.available and rain.value is not None and rain.value >= 3:
        items.append(f"Heaviest forecast 24-hour rainfall is {rain.value:.2f} in; check drainage, official flood warnings, and affected roads")
    for r in rules:
        if r.triggered and r.planning_only and r.hazard in ("tropical", "coastal", "flood"):
            items.append(f"Prepare for {r.observed_value if r.metric == 'alert_present' else r.label}; verify official timing and safe commute routes")
    for r in rules:
        if r.triggered and r.metric == "obs_freezing_precip_hours_3h":
            items.append("Freezing precipitation observed at the facility ASOS in the last 3 h")
    if not items and sufficiency is not None and sufficiency.provisional:
        items.append("Backup forecast in use: verify local warnings and missing measurements before the next commute")
    elif not items and sufficiency is not None and not sufficiency.supports_all_clear:
        items.append("Recheck for current data: the forecast is missing or out of date, so quiet output here is not an all-clear")
    elif not items:
        items.append("No alerts starting or ending and no forecast thresholds approached in the next 6 hours")
    return items[:8]


def feature_vector(ctx: Context, rules: list[RuleResult], hazards: dict[str, HazardResult], facility: Facility) -> dict[str, float]:
    s = ctx.signals

    def val(k, default=0.0):
        x = s.get(k)
        return float(x.value) if x is not None and x.available and x.value is not None else default

    def alert_level(hz):
        lv = [r.level for r in rules if r.hazard == hz and r.metric == "alert_present" and r.triggered]
        return float(max(lv, default=0))

    tz = ZoneInfo(facility.timezone)
    peak = [h.time_of_peak for h in hazards.values() if h.level > 0 and h.time_of_peak]
    peak_hour = float(utc(min(peak)).astimezone(tz).hour) if peak else -1.0
    hours_to_peak = (utc(min(peak)) - ctx.as_of).total_seconds() / 3600 if peak else 48.0
    result = {
        "winter_alert_level": alert_level("winter"),
        "wind_alert_level": alert_level("wind"),
        "cold_alert_level": alert_level("cold"),
        "fcst_ice_in": val("fcst_ice_24h_in"),
        "fcst_snow_in": val("fcst_snow_24h_in"),
        "max_gust_mph": val("max_gust_mph"),
        "road_worst_rank": val("road_worst_rank"),
        "min_apparent_f": val("fcst_min_apparent_24h_f", 32.0),
        "spc_rank": max(val("spc_day1_rank", -1.0), -1.0),
        "obs_freezing_hours": val("obs_freezing_precip_hours_3h"),
        "peak_local_hour": peak_hour,
        "hours_to_peak": max(-12.0, min(48.0, hours_to_peak)),
        "winter_level": float(hazards["winter"].level),
        "wind_level": float(hazards["wind"].level),
    }
    if facility.state == "NC":
        result.update({"rain_24h_in": val("fcst_rain_24h_in"),
                       "tropical_alert_level": alert_level("tropical"), "coastal_alert_level": alert_level("coastal"),
                       "flood_alert_level": alert_level("flood"),
                       "tropical_level": float(hazards.get("tropical").level) if "tropical" in hazards else 0.0,
                       "coastal_level": float(hazards.get("coastal").level) if "coastal" in hazards else 0.0,
                       "flood_level": float(hazards.get("flood").level) if "flood" in hazards else 0.0})
    return result


def assess(inputs: list[NormalizedInput], statuses: list[SourceStatus], facility: Facility, as_of: datetime,
           mode: str, th: Thresholds | None = None, employees: list[dict] | None = None) -> Assessment:
    th = th or load_thresholds(facility=facility)
    timing = {**th.timing, "am_commute": facility.commute_windows.get("am", th.timing["am_commute"]),
              "pm_commute": facility.commute_windows.get("pm", th.timing["pm_commute"])}
    th = th.model_copy(update={"timing": timing})
    ctx = extract(inputs, as_of, employees, horizon_end(utc(as_of), facility, timing), facility.timezone, facility)
    rules = evaluate_rules(ctx, th)
    hazards = score_hazards(rules)
    posture = decide(hazards, rules, ctx.as_of, facility, th)
    confidence = conf.compute(statuses, inputs, ctx, rules, hazards, mode, facility)
    changes = what_would_change(ctx, th, facility, posture.posture, rules)
    sufficiency = assess_sufficiency(inputs, statuses, hazards, rules, posture, ctx.as_of, mode, facility.timezone, timing, facility)
    if facility.state == "NC" and sufficiency.status != "sufficient":
        cap = 0.49 if sufficiency.status == "insufficient" else 0.65
        confidence.score = min(confidence.score, cap)
        confidence.level = "low" if confidence.score < 0.5 else "medium"
        confidence.factors.append(conf.Factor(name="coastal_evidence_gaps", score=cap, weight=0,
                                              explanation="Wilmington has incomplete local weather or coastal evidence; confidence is capped. This is not an accuracy probability."))
    readiness = assess_readiness(hazards, rules, posture, confidence, ctx.alerts, ctx.as_of, facility, th, sufficiency)
    return Assessment(
        as_of=ctx.as_of, mode=mode, signals=ctx.signals, rules=rules, hazards=hazards, posture=posture,
        confidence=confidence, changes=changes, readiness=readiness, sufficiency=sufficiency,
        watch_next_6h=_watch(ctx, rules, facility, sufficiency),
        features=feature_vector(ctx, rules, hazards, facility), alerts=ctx.alerts,
    )


def json_ready(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, list):
        return [json_ready(x) for x in obj]
    if isinstance(obj, dict):
        return {k: json_ready(v) for k, v in obj.items()}
    return obj
