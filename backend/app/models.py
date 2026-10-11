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


class SnapshotInterpretation(SQLModel, table=True):
    """AI-written brief added to a snapshot after it was saved. Append-only; the snapshot itself
    keeps its deterministic template brief and is never edited."""

    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: str = Field(index=True, foreign_key="snapshot.snapshot_id")
    created_at: datetime
    status: str  # ok | failed
    model_id: str
    prompt_version: str
    seconds: float
    ai_json: str
    content_sha256: str


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


class NotificationPackage(SQLModel, table=True):
    id: str = Field(primary_key=True)
    decision_id: int = Field(unique=True, foreign_key="decision.id")
    facility_id: str = Field(index=True)
    decision_day: str = Field(index=True)
    state_json: str


class NotificationClock(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    simulated_now: datetime | None = None


class NotificationAudit(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    package_id: str = Field(index=True)
    at: datetime
    actor: str
    action: str
    detail_json: str


class DecisionCameraArchive(SQLModel, table=True):
    decision_id: int = Field(primary_key=True, foreign_key="decision.id")
    manifest_json: str


class DecisionCameraFrame(SQLModel, table=True):
    id: str = Field(primary_key=True)
    decision_id: int = Field(index=True, foreign_key="decision.id")
    image: bytes


class DecisionContext(SQLModel, table=True):
    """How a decision was made: in demo mode (cached weather) or as a seeded example. Written once."""
    decision_id: int = Field(primary_key=True, foreign_key="decision.id")
    demo_mode: bool = False
    example: bool = False


class DecisionReview(SQLModel, table=True):
    """How a past decision turned out. Append-only: the newest manager review wins, else the newest AI review."""
    id: int | None = Field(default=None, primary_key=True)
    decision_id: int = Field(index=True, foreign_key="decision.id")
    source: str  # manager | ai | template (deterministic weather check when AI is unavailable)
    verdict: str  # good_call | too_lenient | too_strict | mixed
    confidence: float | None = None
    note: str | None = None
    reviewer: str
    created_at: datetime
    evidence_json: str = "{}"
