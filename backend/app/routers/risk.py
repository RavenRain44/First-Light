"""Errors & risk trade-offs: weather error types from the backtest, plus an experimental action-risk view."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from app import historical, snapshots
from app.config import settings
from app.facility import load_facility, facility_employees
from engine.action_risk import assess_actions
from engine.scoring import load_thresholds

router = APIRouter(prefix="/api")

VALIDATION = settings.data_dir / "backtesting" / "metrics" / "recall-hourly.json"


def validation() -> dict | None:
    """Hourly-check validation (scripts/recall_backtest.py --forecasts --checks hourly), labelled stale if the
    thresholds changed since it was generated."""
    if not VALIDATION.exists():
        return None
    r = json.loads(VALIDATION.read_text(encoding="utf-8"))
    keep = ("2019-2026 (with forecasts)", "2023-2026 (held out)", "2019-2022 (tune)", "1996-2018")
    return {"generated_at": r.get("generated_at"), "thresholds_version": r["thresholds_version"],
            "current": r["thresholds_sha256"] == load_thresholds().sha256, "checks": r["checks"], "label": r["label"],
            "periods": {k: r["periods"][k] for k in keep if k in r["periods"]}, "all_years": r["all"]}


def _facility(facility_id=None):
    try: return load_facility(facility_id)
    except KeyError: raise HTTPException(422,"Unknown facility") from None



@router.get("/risk-tradeoffs")
def risk_tradeoffs(snapshot_id: str | None = None, time: str = "04:00", facility_id: str | None = None):
    """Read-only. Never records a decision, changes the suggestion or sends notifications."""
    facility=_facility(facility_id)
    snap = (snapshots.get(snapshot_id) or historical.lookup(snapshot_id)) if snapshot_id else None
    if snapshot_id and (not snap or snap["facility"]["id"] != facility.id):
        raise HTTPException(404, "snapshot not found")
    scores = historical.overview(facility.id)["metrics_by_time"].get(time) or {}
    from app.risk_experiment import saved_report
    # The committed hourly validation measures Ames station weather and policy.
    return {"validation": validation() if facility.id == "IA-AMES-SC" else None,
            "experiment":saved_report(facility.id) if time=="04:00" else None,"errors": scores.get("error_analysis", {}), "range": scores.get("range"), "evaluation_time": time,
            "actions": assess_actions(snap, facility_employees(facility), load_thresholds(facility=facility).timing) if snap else None}
