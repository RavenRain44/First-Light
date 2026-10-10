"""Historical events (backtest), replay and analogs."""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from adapters.base import utc
from app import snapshots
from app.db import session
from app.facility import load_facility
from app.models import HistoryEvent, Snapshot
from engine import analogs

router = APIRouter(prefix="/api")


def _event_dict(e: HistoryEvent) -> dict:
    return {"id": e.id, "name": e.name, "hazard": e.hazard, "start": utc(e.start).isoformat(), "end": utc(e.end).isoformat(),
            "impact_day": e.impact_day, "summary": e.summary, "verification": json.loads(e.verification_json),
            "outcome": json.loads(e.outcome_json), "backtest": json.loads(e.backtest_json)}


@router.get("/history/events")
def events():
    with session() as s:
        rows = s.exec(select(HistoryEvent).order_by(HistoryEvent.start)).all()
        return [_event_dict(e) for e in rows]


@router.get("/history/events/{event_id}")
def event(event_id: str):
    with session() as s:
        e = s.get(HistoryEvent, event_id)
        if not e:
            raise HTTPException(404, "event not found")
        timeline = s.exec(select(Snapshot).where(Snapshot.event_id == event_id, Snapshot.mode == "backtest")
                          .order_by(Snapshot.as_of)).all()
        d = _event_dict(e)
        d["timeline"] = [{"snapshot_id": r.snapshot_id, "as_of": utc(r.as_of).isoformat(), "posture": r.posture,
                          "confidence": r.confidence, "scores": {k: v["score"] for k, v in json.loads(r.hazards_json).items()},
                          "label": "simulated by rules (backtest)"} for r in timeline]
        return d


@router.get("/history/events/{event_id}/replay")
async def replay(event_id: str, as_of: datetime):
    """Full snapshot "as of" a moment in a historical event, using only data that existed then.

    Reuses the stored backtest snapshot for that hour when there is one (built by
    scripts/build_history.py); otherwise evaluates now in replay mode.
    """
    as_of = utc(as_of)
    with session() as s:
        if not s.get(HistoryEvent, event_id):
            raise HTTPException(404, "event not found")
        row = s.exec(select(Snapshot).where(Snapshot.event_id == event_id, Snapshot.as_of == as_of.replace(tzinfo=None))
                     .order_by(Snapshot.created_at.desc())).first()
    if row is not None:
        snap = snapshots.row_to_dict(row)
        if not snap["analogs"]:
            snap["analogs"] = analogs.find_analogs(snap["features"], exclude_event=event_id)
        return snap
    return await snapshots.evaluate(load_facility(), as_of, "replay", event_id=event_id)


@router.get("/analogs")
def get_analogs(snapshot_id: str):
    snap = snapshots.get(snapshot_id)
    if not snap:
        raise HTTPException(404, "snapshot not found")
    return analogs.find_analogs(snap["features"], exclude_event=snap.get("event_id"))
