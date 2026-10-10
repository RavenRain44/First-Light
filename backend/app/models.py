"""SQLite tables. Snapshots and decisions are append-only (enforced by triggers in db.py)."""
from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class Snapshot(SQLModel, table=True):
    """Immutable record of one evaluation: everything known, when, and what the rules said."""

    snapshot_id: str = Field(primary_key=True)
    facility_id: str = Field(index=True)
    as_of: datetime = Field(index=True)
    created_at: datetime
    mode: str = Field(index=True)  # live | replay | backtest | livecheck
    event_id: str | None = Field(default=None, index=True)
    posture: str
    opm_label: str
    confidence: str
    confidence_score: float
    thresholds_version: str
    thresholds_sha256: str
    model_id: str
    prompt_version: str
    content_sha256: str
    facility_json: str
    roster_json: str
    inputs_json: str
    sources_json: str
    signals_json: str
    rules_json: str
    hazards_json: str
    posture_json: str
    confidence_json: str
    changes_json: str
    readiness_level: str = Field(default="", index=True)
    readiness_json: str = "{}"
    watch_json: str
    analogs_json: str
    features_json: str
    ai_json: str


class Decision(SQLModel, table=True):
    """What the human decided for a snapshot. Corrections are new rows, never edits."""

    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: str = Field(index=True, foreign_key="snapshot.snapshot_id")
    facility_id: str = Field(index=True)
    decided_by: str
    decision_posture: str
    recommended_posture: str
    agreed_with_recommendation: bool
    override_reason: str | None = None
    notes: str | None = None
    decided_at: datetime


class HistoryEvent(SQLModel, table=True):
    """A verified past event used for backtesting and analogs."""

    id: str = Field(primary_key=True)
    name: str
    hazard: str
    start: datetime
    end: datetime
    impact_day: str
    summary: str
    verification_json: str
    outcome_json: str
    backtest_json: str
