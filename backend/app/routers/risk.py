"""Errors & risk trade-offs: weather error types from the backtest, plus an experimental action-risk view."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import historical, snapshots
from app.facility import load_employees
from engine.action_risk import assess_actions
from engine.scoring import load_thresholds

router = APIRouter(prefix="/api")


@router.get("/risk-tradeoffs")
def risk_tradeoffs(snapshot_id: str | None = None, time: str = "04:00"):
    """Read-only. Never records a decision, changes the suggestion or sends notifications."""
    snap = (snapshots.get(snapshot_id) or historical.lookup(snapshot_id)) if snapshot_id else None
    if snapshot_id and not snap:
        raise HTTPException(404, "snapshot not found")
    scores = historical.overview()["metrics_by_time"].get(time) or {}
    return {"errors": scores.get("error_analysis", {}), "range": scores.get("range"), "evaluation_time": time,
            "actions": assess_actions(snap, load_employees(), load_thresholds().timing) if snap else None}
