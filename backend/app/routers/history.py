"""Historical events (backtest), replay and analogs."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from adapters.base import utc
from app import snapshots, replay_timeline, replay_controls, nc_replay
from app.db import session
from app.facility import load_facility
from app.models import HistoryEvent, Snapshot
from ai import fallback
from engine import analogs

router = APIRouter(prefix="/api")

def _facility(facility_id=None):
    try: return load_facility(facility_id)
    except KeyError: raise HTTPException(422,"Unknown facility") from None



@router.get("/replay/timeline")
async def custom_timeline(as_of: datetime, facility_id: str | None = None):
    """25 hourly evaluations centered on the exact requested instant (including minutes).

    Only the separately selected report is persisted/enriched; these ribbon cells
    use the same deterministic rules without modifying recorded historical events.
    """
    as_of = utc(as_of)
    try:
        as_of - timedelta(hours=replay_timeline.WINDOW_HOURS)
        as_of + timedelta(hours=replay_timeline.WINDOW_HOURS)
    except OverflowError:
        raise HTTPException(422, "Replay date is outside the supported range") from None
    return await replay_timeline.build_timeline(_facility(facility_id), as_of)


def _event_dict(e: HistoryEvent) -> dict:
    name = e.name.replace("(control case)", "(mild-weather case)") if e.id == "advisory-2025-02-05" else e.name
    return {"id": e.id, "facility_id": e.facility_id, "name": name, "hazard": e.hazard, "start": utc(e.start).isoformat(), "end": utc(e.end).isoformat(),
            "impact_day": e.impact_day, "summary": e.summary, "verification": json.loads(e.verification_json),
            "outcome": json.loads(e.outcome_json), "backtest": json.loads(e.backtest_json)}


@router.get("/history/events")
def events(facility_id: str | None = None):
    facility=_facility(facility_id)
    if facility.id==nc_replay.FACILITY_ID:return nc_replay.events()
    with session() as s:
        rows = s.exec(select(HistoryEvent).where(HistoryEvent.facility_id==facility.id).order_by(HistoryEvent.start)).all()
        return [_event_dict(e) for e in rows if e.id != replay_controls.CONTROL_ID] + [replay_controls.event()]


@router.get("/history/events/{event_id}")
def event(event_id: str, facility_id: str | None = None):
    facility=_facility(facility_id)
    if facility.id==nc_replay.FACILITY_ID:return nc_replay.event(event_id)
    if event_id == replay_controls.CONTROL_ID:
        return replay_controls.event()
    with session() as s:
        e = s.get(HistoryEvent, event_id)
        if not e or e.facility_id!=facility.id:
            raise HTTPException(404, "event not found")
        timeline = s.exec(select(Snapshot).where(Snapshot.event_id == event_id, Snapshot.facility_id == facility.id, Snapshot.mode == "backtest")
                          .order_by(Snapshot.as_of)).all()
        d = _event_dict(e)
        d["timeline"] = [{"snapshot_id": r.snapshot_id, "as_of": utc(r.as_of).isoformat(), "posture": r.posture,
                          "confidence": r.confidence, "readiness": r.readiness_level or None, "scores": {k: v["score"] for k, v in json.loads(r.hazards_json).items()},
                          "label": "simulated by rules (backtest)"} for r in timeline]
        return d


@router.get("/history/events/{event_id}/replay")
async def replay(event_id: str, as_of: datetime, facility_id: str | None = None):
    """Full snapshot "as of" a moment in a historical event, using only data that existed then.

    Reuses the stored backtest snapshot for that hour when there is one (built by
    scripts/build_history.py); otherwise evaluates now in replay mode.
    """
    facility=_facility(facility_id)
    as_of = utc(as_of)
    if facility.id==nc_replay.FACILITY_ID:return nc_replay.replay(event_id,as_of,use_ai=True)
    if event_id == replay_controls.CONTROL_ID:
        return replay_controls.replay(as_of)
    with session() as s:
        candidate=s.get(HistoryEvent,event_id)
        if not candidate or candidate.facility_id!=facility.id:
            raise HTTPException(404, "event not found")
        row = s.exec(select(Snapshot).where(Snapshot.event_id == event_id, Snapshot.facility_id == facility.id, Snapshot.as_of == as_of)
                     .order_by(Snapshot.created_at.desc())).first()
    if row is not None:
        snap = snapshots.row_to_dict(row)
        if not snap["analogs"]:
            # Backtest rows are built before the library exists; analogs are attached at read time
            # (not stored, so the snapshot itself stays untouched).
            snap["analogs"] = analogs.find_analogs(snap["features"], exclude_event=event_id, facility_id=facility.id, mode="replay")
            snap["ai"]["analog_comparison"] = fallback.build(snap, snap["analogs"]).analog_comparison
        return snapshots.ensure_interpretation(snap)
    return await snapshots.evaluate(facility, as_of, "replay", event_id=event_id)


@router.get("/analogs")
def get_analogs(snapshot_id: str, facility_id: str | None = None):
    facility=_facility(facility_id)
    snap = snapshots.get(snapshot_id)
    if not snap or snap["facility"]["id"]!=facility.id:
        raise HTTPException(404, "snapshot not found")
    return analogs.find_analogs(snap["features"], exclude_event=snap.get("event_id"),facility_id=facility.id,mode=snap['mode'])
