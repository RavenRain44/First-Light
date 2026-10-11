"""Errors & risk trade-offs: weather error types from the backtest, plus an experimental action-risk view."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import historical, snapshots
from app.facility import load_employees, load_facility, facility_employees
from engine.action_risk import assess_actions
from engine.scoring import load_thresholds

router = APIRouter(prefix="/api")

def _facility(facility_id=None):
    try: return load_facility(facility_id)
    except KeyError: raise HTTPException(422,"Unknown facility") from None



@router.get("/risk-tradeoffs")
def risk_tradeoffs(snapshot_id: str | None = None, time: str = "04:00", facility_id: str | None = None):
    facility=_facility(facility_id)
    """Read-only. Never records a decision, changes the suggestion or sends notifications."""
    snap = (snapshots.get(snapshot_id) or historical.lookup(snapshot_id)) if snapshot_id else None
    if snapshot_id and (not snap or snap["facility"]["id"] != facility.id):
        raise HTTPException(404, "snapshot not found")
    scores = historical.overview(facility.id)["metrics_by_time"].get(time) or {}
    from app.risk_experiment import saved_report
    return {"experiment":saved_report(facility.id) if time=="04:00" else None,"errors": scores.get("error_analysis", {}), "range": scores.get("range"), "evaluation_time": time,
            "actions": assess_actions(snap, facility_employees(facility), load_thresholds(facility=facility).timing) if snap else None}
