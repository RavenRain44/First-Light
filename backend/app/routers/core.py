"""Facility, snapshots, evaluation, charts, roads, thresholds, decisions."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlmodel import select

from adapters.base import Facility, utc
from adapters.cache import SourceUnavailable
from adapters.iem_roads import RANK_LABELS, fetch_road_geojson
from app import snapshots
from app.config import settings
from app.db import session
from app.facility import get_facility, list_facilities, load_employees, roster_summary
from app.models import Decision, DecisionContext, HistoryEvent
from engine import sufficiency
from engine.features import wind_chill_f
from engine.posture import ORDER
from engine.scoring import load_thresholds

router = APIRouter(prefix="/api")
_facility_live_locks: dict[str, asyncio.Lock] = {}


def _live_lock_for(facility_id: str) -> asyncio.Lock:
    return _facility_live_locks.setdefault(facility_id, asyncio.Lock())


def _facility(facility_id: str | None):
    try:
        return get_facility(facility_id)
    except KeyError:
        raise HTTPException(404, f"unknown facility {facility_id}")


def _check_snapshot_facility(snap: dict, facility_id: str | None) -> dict:
    if facility_id is not None:
        selected = _facility(facility_id).id
        facility = snap["facility"]
        own_hypothetical = snap.get("mode") == "livecheck" and facility.get("hypothetical") is True \
            and (facility.get("provider_settings") or {}).get("origin_facility_id") == selected
        if selected != facility["id"] and not own_hypothetical:
            raise HTTPException(404, "Snapshot does not belong to the selected facility")
    return snap


@router.get("/health")
def health():
    return {"ok": True, "demo_mode": settings.demo_mode, "model_provider": settings.model_provider,
            "inference": {"provider": "akamai", "model": settings.akamai_model_id,
                          "enabled": settings.model_provider != "none" and (
                              bool(settings.akamai_api_key) or settings.strands_fallback_enabled),
                          "key_configured": bool(settings.akamai_api_key),
                          "strands_fallback_enabled": settings.strands_fallback_enabled,
                          "strands_model": settings.strands_model_id},
            "time": datetime.now(timezone.utc).isoformat()}


@router.get("/facilities")
def facilities():
    return [f.model_dump() for f in list_facilities()]


@router.get("/facility")
def facility(facility_id: str | None = None):
    f = _facility(facility_id)
    emps = load_employees()
    return {"facility": f.model_dump(), "roster": roster_summary(f),
            "employees": [e for e in emps if e["assigned_facility"] == f.id or e["this_week_location"] == f.id]}


@router.get("/snapshot/latest")
async def snapshot_latest(facility_id: str | None = None, max_age_seconds: int | None = None):
    """Latest live snapshot; re-evaluates when older than SNAPSHOT_STALE_SECONDS."""
    f = _facility(facility_id)
    max_age = settings.snapshot_stale_seconds if max_age_seconds is None else max_age_seconds
    async with _live_lock_for(f.id):
        snap = snapshots.latest(f.id, "live")
        stale = snap is None or (datetime.now(timezone.utc) - datetime.fromisoformat(snap["created_at"])).total_seconds() > max_age
        if snap is None or (stale and not settings.demo_mode):  # demo data never changes; reuse it
            snap = await snapshots.evaluate(f, None, "live")
    return snapshots.ensure_interpretation(snap)


class EvaluateRequest(BaseModel):
    facility_id: str | None = None
    as_of: datetime | None = None
    mode: Literal["live", "replay"] = "live"
    event_id: str | None = None
    use_ai: bool = True


@router.post("/evaluate")
async def evaluate(req: EvaluateRequest, facility_id: str | None = None):
    if req.facility_id and facility_id and req.facility_id != facility_id:
        raise HTTPException(422, "Conflicting facility IDs")
    f = _facility(req.facility_id or facility_id)
    if req.mode == "replay" and req.as_of is None:
        raise HTTPException(422, "replay requires as_of")
    if req.mode == "live":
        if req.as_of is not None:
            raise HTTPException(422, "Live evaluation uses current facility weather; use read-only replay for a selected time")
        async with _live_lock_for(f.id):
            return await snapshots.evaluate(f, None, "live", use_ai=req.use_ai)
    return await snapshots.evaluate(f, utc(req.as_of), "replay", event_id=req.event_id, use_ai=req.use_ai)


@router.get("/snapshot/{snapshot_id}")
async def snapshot(snapshot_id: str, facility_id: str | None = None):
    s = snapshots.get(snapshot_id)
    if not s:
        raise HTTPException(404, "snapshot not found")
    return snapshots.ensure_interpretation(_check_snapshot_facility(s, facility_id))


@router.get("/snapshot/{snapshot_id}/interpretation")
def snapshot_interpretation(snapshot_id: str, facility_id: str | None = None):
    """AI brief added after the snapshot was saved: pending | ok | failed | none."""
    if facility_id is not None:
        saved = snapshots.get(snapshot_id)
        if not saved:
            raise HTTPException(404, "snapshot not found")
        _check_snapshot_facility(saved, facility_id)
    return snapshots.interpretation(snapshot_id)


@router.post("/snapshot/{snapshot_id}/interpretation", status_code=202)
async def regenerate_snapshot_interpretation(snapshot_id: str, facility_id: str | None = None):
    """Regenerate the AI brief for this snapshot now (runs in the background)."""
    if facility_id is not None:
        saved = snapshots.get(snapshot_id)
        if not saved:
            raise HTTPException(404, "snapshot not found")
        _check_snapshot_facility(saved, facility_id)
    result = snapshots.regenerate_interpretation(snapshot_id)
    if result is None:
        raise HTTPException(404, "snapshot not found")
    if result["status"] == "unavailable":
        raise HTTPException(409, "AI brief unavailable: no inference provider is configured")
    return result


@router.get("/snapshots")
def snapshot_history(facility_id: str | None = None, limit: int = 50):
    f = _facility(facility_id)
    return snapshots.history(f.id, limit)


# ----------------------------------------------------------------------------- charts

CHART_METRICS = {
    "wind": ["wind_gust_mph", "wind_speed_mph"],
    "temp": ["temp_f", "apparent_temp_f"],
    "precip": ["ice_in", "snow_in", "qpf_in", "pop_pct", "precip_in", "freezing_precip"],
}
CHART_RULES = {  # rule id -> chart series it is drawn on
    "wind.fcst_gust_warning": "wind", "wind.fcst_gust_advisory": "wind", "wind.destructive_gust": "wind",
    "winter.fcst_ice_quarter_inch": "ice_cum", "winter.fcst_ice_tenth_inch": "ice_cum",
    "winter.fcst_ice_any": "ice_cum", "winter.fcst_snow_advisory_24h": "snow_cum", "winter.fcst_snow_warning_12h": "snow_cum",
    "cold.fcst_wind_chill_advisory": "temp", "cold.fcst_wind_chill_extreme": "temp",
    "flood.heavy_rain_monitor": "rain_cum",
}


def windows_for(start: datetime, end: datetime, f) -> list[dict]:
    tz = ZoneInfo(f.timezone)
    th = load_thresholds(facility=f)
    out = []
    d = start.astimezone(tz).date()
    while d <= end.astimezone(tz).date():
        def at(hhmm):
            h, m = map(int, hhmm.split(":"))
            return datetime(d.year, d.month, d.day, h, m, tzinfo=tz).astimezone(timezone.utc).isoformat()
        if d.weekday() in getattr(f, 'workdays', [0, 1, 2, 3, 4]):
            out.append({"kind": "hours", "label": "Facility hours", "start": at(f.hours["open"]), "end": at(f.hours["close"])})
        am = f.commute_windows.get("am", th.timing["am_commute"])
        pm = f.commute_windows.get("pm", th.timing["pm_commute"])
        out.append({"kind": "am_commute", "label": "AM commute", "start": at(am[0]), "end": at(am[1])})
        out.append({"kind": "pm_commute", "label": "PM commute", "start": at(pm[0]), "end": at(pm[1])})
        d += timedelta(days=1)
    return out


def build_timeseries(snap: dict) -> dict:
    # Charts describe the immutable record, including its saved site and hours.
    # Editing the registry later must not move an old decision's commute windows.
    fac = Facility(**snap["facility"])
    as_of = datetime.fromisoformat(snap["as_of"])
    start, end = as_of - timedelta(hours=12), as_of + timedelta(hours=72 if fac.state == "NC" else 48)
    rows: dict[str, dict] = {}
    meta = {}
    for inp in snap["inputs"]:
        if inp["kind"] != "series" or inp["id"].startswith("unused."):
            continue
        prefix = "obs" if inp["role"] == "observation" else "fcst"
        key = f"{prefix}_{inp['metric']}"
        data = inp.get("data") or {}
        station = data.get("station_id") or data.get("gauge_id")
        if inp["metric"] == "water_level_ft" and station:
            key += f"_{station}"
        meta[key] = {k: inp.get(k) for k in ("id", "source", "source_url", "fetched_at", "source_time", "unit", "note")}
        meta[key].update(metric=inp["metric"], role=inp["role"], input_ids=[inp["id"]])
        if data:
            meta[key]["provenance"] = data
            for field in ("station_id", "gauge_id", "station_name", "datum", "flood_stage_ft", "flood_thresholds_ft", "scope"):
                if field in data:
                    meta[key][field] = data[field]
        rain_alias = "fcst_rain_in" if fac.state == "NC" and prefix == "fcst" and inp["metric"] == "qpf_in" else None
        if rain_alias:
            meta[rain_alias] = {**meta[key], "metric": "rain_in"}
        for p in inp["series"]:
            t = datetime.fromisoformat(p["t"])
            if not (start <= t <= end) or p["v"] is None:
                continue
            if prefix == "fcst" and t < as_of - timedelta(hours=1):
                continue
            if prefix == "obs" and t > as_of:
                continue
            row = rows.setdefault(utc(t).isoformat(), {"t": utc(t).isoformat()})
            row[key] = p["v"]
            if rain_alias:
                row[rain_alias] = p["v"]
    ordered = sorted(rows.values(), key=lambda r: r["t"])
    # Archived NBS has temperature and wind but no separate feels-like series.
    # Render the same derived quantity the recorded cold signal used, from saved
    # inputs only. This enriches the chart response without rewriting a snapshot.
    apparent = snap.get("signals", {}).get("fcst_min_apparent_24h_f", {})
    derived = apparent.get("available") and "fcst.temp_f" in apparent.get("input_ids", [])
    if derived and "fcst_apparent_temp_f" not in meta:
        for r in ordered:
            if datetime.fromisoformat(r["t"]) < as_of.replace(minute=0, second=0, microsecond=0):
                continue
            if isinstance(r.get("fcst_temp_f"), (int, float)):
                # The engine uses zero wind when the saved forecast has no wind at
                # this hour; the formula then returns temperature unchanged.
                r["fcst_apparent_temp_f"] = round(wind_chill_f(r["fcst_temp_f"], r.get("fcst_wind_speed_mph", 0.0)), 1)
        if any("fcst_apparent_temp_f" in r for r in ordered):
            meta["fcst_apparent_temp_f"] = {**meta["fcst_temp_f"], "unit": "degF",
                "note": "Calculated from the saved forecast temperature and wind with the NWS wind chill formula; missing wind uses temperature unchanged.",
                "derived": True, "input_ids": apparent["input_ids"]}
    ice = snow = 0.0
    for r in ordered:  # running forecast totals from as_of forward, for threshold comparison
        if datetime.fromisoformat(r["t"]) >= as_of.replace(minute=0, second=0, microsecond=0):
            if "fcst_ice_in" in r:
                ice += r["fcst_ice_in"]
                r["fcst_ice_cum"] = round(ice, 3)
            if "fcst_snow_in" in r:
                snow += r["fcst_snow_in"]
                r["fcst_snow_cum"] = round(snow, 2)
    # Thresholds were saved with the assessment; use those values rather than
    # today's policy when opening a historical decision.
    lines = [{"chart": CHART_RULES[r["rule_id"]], "value": r["threshold"],
              "label": f"{r['rule_id'].split('.', 1)[1].replace('_', ' ')} ({r['threshold']:g} {r['unit']})",
              "rule_id": r["rule_id"], "verified": r["verified"], "level": r["posture_effect"]}
             for r in snap.get("rules", []) if r["rule_id"] in CHART_RULES]
    return {"snapshot_id": snap["snapshot_id"], "as_of": snap["as_of"], "timezone": snap["facility"]["timezone"],
            "rows": ordered, "meta": meta, "threshold_lines": lines, "windows": windows_for(start, end, fac)}


@router.get("/timeseries")
async def timeseries(facility_id: str | None = None, snapshot_id: str | None = None, as_of: datetime | None = None):
    if snapshot_id:
        snap = snapshots.get(snapshot_id)
        if not snap:
            raise HTTPException(404, "snapshot not found")
        _check_snapshot_facility(snap, facility_id)
    elif as_of:
        snap = await snapshots.evaluate(_facility(facility_id), utc(as_of), "replay")
    else:
        snap = await snapshot_latest(facility_id)
    return build_timeseries(snap)


# ----------------------------------------------------------------------------- roads

@router.get("/roads")
async def roads(facility_id: str | None = None, as_of: datetime | None = None):
    f = _facility(facility_id)
    t = utc(as_of) if as_of else datetime.now(timezone.utc)
    emps = load_employees()
    here = [e for e in emps if e["this_week_location"] == f.id and not e["teleworking_today"]]
    corridors = []
    source = "Iowa DOT winter road conditions via IEM"
    ranks = RANK_LABELS
    fetch = fetch_road_geojson
    if f.state == "NC":
        from adapters.ncdot import fetch_road_geojson as fetch_nc_roads
        fetch, source = fetch_nc_roads, "NCDOT reported incidents and restrictions"
        ranks = {0: "No restriction reported", 4: "Reported restriction", 5: "Reported closure"}
    try:
        gj, r = await fetch(f, t)
        status, detail, url, fetched = "ok", None, r.url, r.fetched_at.isoformat()
        if not gj["features"]:
            status, detail = "empty", ("No NCDOT incident returned for these corridors; unreported flooding and access remain unknown."
                                       if f.state == "NC" else "Iowa DOT reports no winter road conditions for this time (reporting is seasonal, roughly Nov-Apr).")
    except SourceUnavailable as e:
        gj, status, detail, url, fetched = {"type": "FeatureCollection", "features": []}, "unavailable", str(e), None, None
    for c in f.corridors:
        segs = [x["properties"] for x in gj["features"] if c.id in x["properties"]["corridors"] and x["properties"]["rank"] is not None]
        worst = max(segs, key=lambda s: s["rank"]) if segs else None
        corridors.append({
            "id": c.id, "name": c.name, "coordinates": c.coordinates,
            "worst_rank": worst["rank"] if worst else None,
            "worst_label": worst["label"] if worst else None,
            "worst_rank_label": ranks.get(worst["rank"], worst["label"]) if worst else "No report",
            "worst_updated": worst.get("utc_valid") if worst else None,
            "n_segments": len(segs),
            "commuters_in_building": sum(1 for e in here if e["commute_corridor"] == c.id),
            "commuters_assigned": sum(1 for e in emps if e["assigned_facility"] == f.id and e["commute_corridor"] == c.id),
        })
    local = sum(1 for e in here if e["commute_corridor"] == "local")
    return {"as_of": t.isoformat(), "status": status, "detail": detail, "source_url": url, "fetched_at": fetched,
            "source": source, "rank_labels": ranks,
            "geojson": gj, "corridors": corridors, "local_commuters_in_building": local,
            "facility": {"lat": f.lat, "lon": f.lon, "name": f.name}}


# ----------------------------------------------------------------------------- thresholds

@router.get("/thresholds")
def thresholds(facility_id: str | None = None):
    f = _facility(facility_id)
    th = load_thresholds(facility=f)
    with session() as s:
        events = s.exec(select(HistoryEvent).where(HistoryEvent.facility_id == f.id).order_by(HistoryEvent.start)).all()
    backtest = [{"event_id": e.id, "name": e.name, "hazard": e.hazard, "impact_day": e.impact_day,
                 **json.loads(e.backtest_json)} for e in events]
    return {"facility_id": f.id, "version": th.version, "sha256": th.sha256, "rules": [r.model_dump() for r in th.rules],
            "postures": th.postures, "timing": th.timing, "readiness": th.raw.get("readiness"),
            "unverified_count": sum(1 for r in th.rules if not r.verified), "backtest": backtest}


# ----------------------------------------------------------------------------- decisions

class DecisionIn(BaseModel):
    snapshot_id: str
    facility_id: str | None = None
    decided_by: str = Field(min_length=2, max_length=120)
    decision_posture: str
    override_reason: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("decided_by")
    @classmethod
    def manager_required(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Manager name required")
        return value


@router.post("/decisions", status_code=201)
def record_decision(d: DecisionIn, background_tasks: BackgroundTasks, facility_id: str | None = None):
    snap = snapshots.get(d.snapshot_id)
    if not snap:
        raise HTTPException(404, "snapshot not found")
    if d.decision_posture not in ORDER:
        raise HTTPException(422, f"decision_posture must be one of {ORDER}")
    if d.facility_id and facility_id and d.facility_id != facility_id:
        raise HTTPException(422, "Conflicting facility IDs")
    _check_snapshot_facility(snap, d.facility_id or facility_id)
    if snap["mode"] != "live" or snap.get("historical_context") or snap["facility"].get("hypothetical"):
        raise HTTPException(422, "Historical replay and hypothetical assessments are read-only; record a decision from live facility weather")
    evidence = sufficiency.for_snapshot(snap)
    reason = (d.override_reason or "").strip() or None
    manual = bool(evidence.get("reason_required"))
    # Insufficient, unrecorded or provisional evidence needs an explicit manager reason.
    agreed = d.decision_posture == snap["posture"]["posture"] and not manual
    if manual and not reason:
        raise HTTPException(422, "override_reason is required: evidence is provisional or insufficient "
                                 f"({evidence['status']}), so this is a manual decision; explain the basis for it")
    if d.decision_posture != snap["posture"]["posture"] and not reason:
        raise HTTPException(422, "override_reason is required when the decision differs from the recommendation")
    row = Decision(snapshot_id=d.snapshot_id, facility_id=snap["facility"]["id"], decided_by=d.decided_by.strip(),
                   decision_posture=d.decision_posture, recommended_posture=snap["posture"]["posture"],
                   agreed_with_recommendation=agreed, override_reason=reason,
                   notes=d.notes, decided_at=datetime.now(timezone.utc))
    basis = ("manual_provisional_forecast" if manual and evidence.get("provisional") and evidence["status"] == "limited"
             else "manual_insufficient_evidence" if manual else "recommendation" if agreed else "override")
    with session() as s:
        s.add(row)
        s.commit()
        s.refresh(row)
        # Demo-mode decisions use cached weather; Past decisions leaves them out.
        s.add(DecisionContext(decision_id=row.id, demo_mode=settings.demo_mode, evidence_status=evidence["status"],
                              decision_basis=basis)); s.commit()
        from app.camera_archive import pending, capture
        s.add(pending(row)); s.commit()
        camera_time = datetime.fromisoformat(snap["as_of"]) if snap["mode"] == "replay" else row.decided_at.replace(tzinfo=timezone.utc)
        background_tasks.add_task(capture, row.id, row.facility_id, camera_time, snap["mode"] == "replay")
        return {**row.model_dump(mode="json"), "label": "real (recorded in this system)",
                "evidence_status": evidence["status"], "decision_basis": basis}


def _with_context(rows: list[Decision], s) -> list[dict]:
    ctx = {c.decision_id: c for c in s.exec(select(DecisionContext).where(DecisionContext.decision_id.in_([r.id for r in rows]))).all()}
    return [{**r.model_dump(mode="json"), "label": "real (recorded in this system)",
             "evidence_status": ctx[r.id].evidence_status if r.id in ctx else "",
             "decision_basis": ctx[r.id].decision_basis if r.id in ctx else ""} for r in rows]


@router.get("/decisions")
def list_decisions(facility_id: str | None = None):
    f = _facility(facility_id)
    with session() as s:
        rows = s.exec(select(Decision).where(Decision.facility_id == f.id).order_by(Decision.decided_at.desc())).all()
        return _with_context(rows, s)


@router.get("/record/{snapshot_id}")
async def decision_record(snapshot_id: str, facility_id: str | None = None):
    """Everything needed to reconstruct one decision: the snapshot plus the human decisions against it."""
    snap = snapshots.get(snapshot_id)
    if not snap:
        raise HTTPException(404, "snapshot not found")
    _check_snapshot_facility(snap, facility_id)
    th = load_thresholds(facility=_facility(snap["facility"]["id"]))
    with session() as s:
        ds = _with_context(s.exec(select(Decision).where(Decision.snapshot_id == snapshot_id).order_by(Decision.decided_at)).all(), s)
    return {"snapshot": snapshots.ensure_interpretation(snap), "decisions": ds,
            "thresholds_current_sha256": th.sha256,
            "thresholds_changed_since": th.sha256 != snap["thresholds_sha256"]}
