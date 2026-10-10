"""Facility, snapshots, evaluation, charts, roads, thresholds, decisions."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlmodel import select

from adapters.base import utc
from adapters.cache import SourceUnavailable
from adapters.iem_roads import RANK_LABELS, fetch_road_geojson
from app import snapshots
from app.config import settings
from app.db import session
from app.facility import get_facility, load_employees, roster_summary
from app.models import Decision, HistoryEvent
from engine.posture import ORDER
from engine.scoring import load_thresholds

router = APIRouter(prefix="/api")
_live_lock = asyncio.Lock()


def _facility(facility_id: str | None):
    try:
        return get_facility(facility_id)
    except KeyError:
        raise HTTPException(404, f"unknown facility {facility_id}")


@router.get("/health")
def health():
    return {"ok": True, "demo_mode": settings.demo_mode, "model_provider": settings.model_provider,
            "inference": {"provider": "akamai", "model": settings.akamai_model_id,
                          "key_configured": bool(settings.akamai_api_key),
                          "aws_fallback_enabled": settings.aws_fallback_enabled},
            "time": datetime.now(timezone.utc).isoformat()}


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
    async with _live_lock:
        snap = snapshots.latest(f.id, "live")
        stale = snap is None or (datetime.now(timezone.utc) - datetime.fromisoformat(snap["created_at"])).total_seconds() > max_age
        if snap is None or (stale and not settings.demo_mode):  # demo data never changes; reuse it
            snap = await snapshots.evaluate(f, None, "live")
    return snap


class EvaluateRequest(BaseModel):
    facility_id: str | None = None
    as_of: datetime | None = None
    mode: Literal["live", "replay"] = "live"
    event_id: str | None = None
    use_ai: bool = True


@router.post("/evaluate")
async def evaluate(req: EvaluateRequest):
    f = _facility(req.facility_id)
    if req.mode == "replay" and req.as_of is None:
        raise HTTPException(422, "replay requires as_of")
    if req.mode == "live":
        async with _live_lock:
            return await snapshots.evaluate(f, None, "live", use_ai=req.use_ai)
    return await snapshots.evaluate(f, utc(req.as_of), "replay", event_id=req.event_id, use_ai=req.use_ai)


@router.get("/snapshot/{snapshot_id}")
def snapshot(snapshot_id: str):
    s = snapshots.get(snapshot_id)
    if not s:
        raise HTTPException(404, "snapshot not found")
    return s


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
}


def windows_for(start: datetime, end: datetime, f) -> list[dict]:
    tz = ZoneInfo(f.timezone)
    th = load_thresholds()
    out = []
    d = start.astimezone(tz).date()
    while d <= end.astimezone(tz).date():
        def at(hhmm):
            h, m = map(int, hhmm.split(":"))
            return datetime(d.year, d.month, d.day, h, m, tzinfo=tz).astimezone(timezone.utc).isoformat()
        if d.weekday() in getattr(f, 'workdays', [0, 1, 2, 3, 4]):
            out.append({"kind": "hours", "label": "Facility hours", "start": at(f.hours["open"]), "end": at(f.hours["close"])})
        out.append({"kind": "am_commute", "label": "AM commute", "start": at(th.timing["am_commute"][0]), "end": at(th.timing["am_commute"][1])})
        out.append({"kind": "pm_commute", "label": "PM commute", "start": at(th.timing["pm_commute"][0]), "end": at(th.timing["pm_commute"][1])})
        d += timedelta(days=1)
    return out


def build_timeseries(snap: dict) -> dict:
    f = _facility(snap["facility"]["id"]) if not snap["facility"].get("hypothetical") else None
    fac = f or type("F", (), snap["facility"])  # hypothetical copies carry their own hours/timezone
    as_of = datetime.fromisoformat(snap["as_of"])
    start, end = as_of - timedelta(hours=12), as_of + timedelta(hours=48)
    rows: dict[str, dict] = {}
    meta = {}
    for inp in snap["inputs"]:
        if inp["kind"] != "series":
            continue
        prefix = "obs" if inp["role"] == "observation" else "fcst"
        key = f"{prefix}_{inp['metric']}"
        meta[key] = {k: inp.get(k) for k in ("id", "source", "source_url", "fetched_at", "source_time", "unit", "note")}
        for p in inp["series"]:
            t = datetime.fromisoformat(p["t"])
            if not (start <= t <= end) or p["v"] is None:
                continue
            if prefix == "fcst" and t < as_of - timedelta(hours=1):
                continue
            if prefix == "obs" and t > as_of:
                continue
            rows.setdefault(p["t"], {"t": utc(t).isoformat()})[key] = p["v"]
    ordered = sorted(rows.values(), key=lambda r: r["t"])
    ice = snow = 0.0
    for r in ordered:  # running forecast totals from as_of forward, for threshold comparison
        if datetime.fromisoformat(r["t"]) >= as_of.replace(minute=0, second=0, microsecond=0):
            if "fcst_ice_in" in r:
                ice += r["fcst_ice_in"]
                r["fcst_ice_cum"] = round(ice, 3)
            if "fcst_snow_in" in r:
                snow += r["fcst_snow_in"]
                r["fcst_snow_cum"] = round(snow, 2)
    th = load_thresholds()
    lines = [{"chart": CHART_RULES[r.id], "value": r.value, "label": f"{r.id.split('.', 1)[1].replace('_', ' ')} ({r.value:g} {r.unit})",
              "rule_id": r.id, "verified": r.verified, "level": r.posture_effect}
             for r in th.rules if r.id in CHART_RULES]
    return {"snapshot_id": snap["snapshot_id"], "as_of": snap["as_of"], "timezone": snap["facility"]["timezone"],
            "rows": ordered, "meta": meta, "threshold_lines": lines, "windows": windows_for(start, end, fac)}


@router.get("/timeseries")
async def timeseries(facility_id: str | None = None, snapshot_id: str | None = None, as_of: datetime | None = None):
    if snapshot_id:
        snap = snapshots.get(snapshot_id)
        if not snap:
            raise HTTPException(404, "snapshot not found")
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
    try:
        gj, r = await fetch_road_geojson(f, t)
        status, detail, url, fetched = "ok", None, r.url, r.fetched_at.isoformat()
        if not gj["features"]:
            status, detail = "empty", "Iowa DOT reports no winter road conditions for this time (reporting is seasonal, roughly Nov-Apr)."
    except SourceUnavailable as e:
        gj, status, detail, url, fetched = {"type": "FeatureCollection", "features": []}, "unavailable", str(e), None, None
    for c in f.corridors:
        segs = [x["properties"] for x in gj["features"] if c.id in x["properties"]["corridors"] and x["properties"]["rank"] is not None]
        worst = max(segs, key=lambda s: s["rank"]) if segs else None
        corridors.append({
            "id": c.id, "name": c.name, "coordinates": c.coordinates,
            "worst_rank": worst["rank"] if worst else None,
            "worst_label": worst["label"] if worst else None,
            "worst_rank_label": RANK_LABELS.get(worst["rank"]) if worst else "No report",
            "worst_updated": worst.get("utc_valid") if worst else None,
            "n_segments": len(segs),
            "commuters_in_building": sum(1 for e in here if e["commute_corridor"] == c.id),
            "commuters_assigned": sum(1 for e in emps if e["assigned_facility"] == f.id and e["commute_corridor"] == c.id),
        })
    local = sum(1 for e in here if e["commute_corridor"] == "local")
    return {"as_of": t.isoformat(), "status": status, "detail": detail, "source_url": url, "fetched_at": fetched,
            "source": "Iowa DOT winter road conditions via IEM", "rank_labels": RANK_LABELS,
            "geojson": gj, "corridors": corridors, "local_commuters_in_building": local,
            "facility": {"lat": f.lat, "lon": f.lon, "name": f.name}}


# ----------------------------------------------------------------------------- thresholds

@router.get("/thresholds")
def thresholds():
    th = load_thresholds()
    with session() as s:
        events = s.exec(select(HistoryEvent).order_by(HistoryEvent.start)).all()
    backtest = [{"event_id": e.id, "name": e.name, "hazard": e.hazard, "impact_day": e.impact_day,
                 **json.loads(e.backtest_json)} for e in events]
    return {"version": th.version, "sha256": th.sha256, "rules": [r.model_dump() for r in th.rules],
            "postures": th.postures, "timing": th.timing, "readiness": th.raw.get("readiness"),
            "unverified_count": sum(1 for r in th.rules if not r.verified), "backtest": backtest}


# ----------------------------------------------------------------------------- decisions

class DecisionIn(BaseModel):
    snapshot_id: str
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
def record_decision(d: DecisionIn):
    snap = snapshots.get(d.snapshot_id)
    if not snap:
        raise HTTPException(404, "snapshot not found")
    if d.decision_posture not in ORDER:
        raise HTTPException(422, f"decision_posture must be one of {ORDER}")
    agreed = d.decision_posture == snap["posture"]["posture"]
    if not agreed and not (d.override_reason and d.override_reason.strip()):
        raise HTTPException(422, "override_reason is required when the decision differs from the recommendation")
    row = Decision(snapshot_id=d.snapshot_id, facility_id=snap["facility"]["id"], decided_by=d.decided_by.strip(),
                   decision_posture=d.decision_posture, recommended_posture=snap["posture"]["posture"],
                   agreed_with_recommendation=agreed, override_reason=(d.override_reason or "").strip() or None,
                   notes=d.notes, decided_at=datetime.now(timezone.utc))
    with session() as s:
        s.add(row)
        s.commit()
        s.refresh(row)
        return {**row.model_dump(mode="json"), "label": "real (recorded in this system)"}


@router.get("/decisions")
def list_decisions(facility_id: str | None = None):
    f = _facility(facility_id)
    with session() as s:
        rows = s.exec(select(Decision).where(Decision.facility_id == f.id).order_by(Decision.decided_at.desc())).all()
        return [{**r.model_dump(mode="json"), "label": "real (recorded in this system)"} for r in rows]


@router.get("/record/{snapshot_id}")
def decision_record(snapshot_id: str):
    """Everything needed to reconstruct one decision: the snapshot plus the human decisions against it."""
    snap = snapshots.get(snapshot_id)
    if not snap:
        raise HTTPException(404, "snapshot not found")
    with session() as s:
        ds = s.exec(select(Decision).where(Decision.snapshot_id == snapshot_id).order_by(Decision.decided_at)).all()
    return {"snapshot": snap, "decisions": [d.model_dump(mode="json") for d in ds],
            "thresholds_current_sha256": load_thresholds().sha256,
            "thresholds_changed_since": load_thresholds().sha256 != snap["thresholds_sha256"]}
