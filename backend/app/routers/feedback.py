"""Explicit grading and inference; authorized, validated policy lifecycle."""
from __future__ import annotations

import secrets
import math
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import feedback, past_decisions, policy, storage
from app.config import settings

router = APIRouter(prefix="/api")


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)
    actor: str = Field(min_length=2, max_length=120)


class Intent(Actor):
    objective: str = Field(min_length=3, max_length=1000)
    correction_reason: str = Field(default="", max_length=1000)
    expected_id: int | None = None


class Grade(Actor):
    verdict: Literal["good_call", "too_lenient", "too_strict", "mixed", "insufficient_evidence"]
    observed_evidence_status: Literal["not_disputed", "disputed"] = "not_disputed"
    achievement: Literal["achieved", "partly_achieved", "not_achieved", "unknown"] = "unknown"
    note: str = Field(default="", max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    correction_reason: str = Field(default="", max_length=1000)
    expected_id: int | None = None

    @field_validator("evidence_refs")
    @classmethod
    def safe_urls(cls, refs):
        for ref in refs:
            u = urlsplit(ref)
            if len(ref) > 1000 or u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
                raise ValueError("Evidence references must be HTTP(S) URLs without credentials")
        return refs


class Costs(Actor):
    false_alarm_cost: float = Field(default=1, gt=0, le=1000)
    missed_disruption_cost: float = Field(default=5, gt=0, le=1000)


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    path: str = Field(max_length=150)
    value: float


class Proposal(Costs):
    category: Literal["weather", "timing", "readiness", "confidence"]
    changes: list[Change] = Field(min_length=1, max_length=3)
    rationale: str = Field(min_length=10, max_length=1000)
    cohort: Literal["baseline", "forecast"] = "forecast"
    minimum_recall: float | None = Field(default=None, ge=0, le=1)
    maximum_false_alarm: float | None = Field(default=None, ge=0, le=1)
    analysis_id: str | None = None


class Version(Actor):
    version: int = Field(ge=1)


def authorized(x_threshold_admin_token: str = Header(default="")):
    if not settings.threshold_admin_token:
        raise HTTPException(503, "Policy activation is disabled. Configure THRESHOLD_ADMIN_TOKEN on the server.")
    if not secrets.compare_digest(x_threshold_admin_token.encode(), settings.threshold_admin_token.encode()):
        raise HTTPException(403, "Manager authorization is required to approve, activate or roll back a policy")


@router.get("/decisions/{did}/grade")
def detail(did: int):
    return feedback.detail(did)


@router.post("/decisions/{did}/intention", status_code=201)
def intention(did: int, r: Intent):
    return feedback.annotate(did, r.actor, r.objective, r.correction_reason, r.expected_id)


@router.post("/decisions/{did}/grade", status_code=201)
def grade(did: int, r: Grade):
    feedback.decision_and_snapshot(did)
    return past_decisions.add_manager_review(did, r.actor, r.verdict, r.note, achievement=r.achievement,
               evidence_refs=r.evidence_refs, correction_reason=r.correction_reason, expected_id=r.expected_id, versioned=True, observed_evidence_status=r.observed_evidence_status)


@router.post("/decisions/{did}/grade/refresh")
async def refresh(did: int):
    detail = feedback.detail(did)
    if detail["status"] == "pending":
        raise HTTPException(409, "The facility decision day has not ended; observed outcome is pending")
    if detail["assessments"] and detail["assessments"][0]["eligible"]:
        return detail  # repeated clicks do not refetch archives or append duplicate assessments
    try:
        await past_decisions.run_review(did, use_ai=False)
    except past_decisions.NotYet as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(503, "Observed weather is unavailable. Try again later; no missing data has been graded as quiet.") from e
    return feedback.detail(did)


@router.get("/feedback/statistics")
def statistics(false_alarm_cost: float = Query(default=1, gt=0, le=1000), missed_disruption_cost: float = Query(default=5, gt=0, le=1000)):
    if not all(math.isfinite(v) for v in (false_alarm_cost, missed_disruption_cost)):
        raise HTTPException(422, "Costs must be finite")
    return feedback.statistics(false_alarm_cost, missed_disruption_cost)


@router.get("/feedback/catalog")
def catalog():
    return {"dataset": feedback.catalog(), "cloud": storage.status()}


@router.get("/feedback/analysis")
def analysis():
    return feedback.latest_analysis()


@router.post("/feedback/analyze")
async def analyze(r: Costs):
    return await feedback.analyze(r.actor, r.false_alarm_cost, r.missed_disruption_cost)


@router.get("/policies")
def policies():
    return policy.overview()


@router.post("/policies", status_code=201)
def propose(r: Proposal):
    if r.analysis_id:
        from app.db import session
        from app.models import FeedbackAnalysis
        with session() as s:
            if not s.get(FeedbackAnalysis, r.analysis_id):
                raise HTTPException(422, "Analysis reference does not exist")
    return policy.propose(r.actor, r.category, [c.model_dump() for c in r.changes], r.rationale, r.cohort,
                         r.false_alarm_cost, r.missed_disruption_cost, r.minimum_recall, r.maximum_false_alarm, r.analysis_id)


@router.get("/policies/{pid}")
def proposal(pid: str):
    return policy.get(pid)


@router.post("/policies/{pid}/evaluate", status_code=202)
async def evaluate(pid: str, r: Version):
    return policy.start(pid, r.actor, r.version)


@router.post("/policies/{pid}/approve", dependencies=[Depends(authorized)])
def approve(pid: str, r: Version):
    return policy.approve(pid, r.actor, r.version)


@router.post("/policies/{pid}/activate", dependencies=[Depends(authorized)])
def activate(pid: str, r: Version):
    return policy.activate(pid, r.actor, r.version)


@router.post("/policies/{pid}/rollback", dependencies=[Depends(authorized)])
def rollback(pid: str, r: Version):
    return policy.rollback(pid, r.actor, r.version)
