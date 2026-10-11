"""Past decisions: similar earlier calls at this facility and how they turned out."""
from __future__ import annotations

from typing import Literal
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, field_validator

from app import past_decisions as past
from app import snapshots
from app.facility import get_facility
from app.db import session
from app.models import Decision

router = APIRouter(prefix="/api")


def _check_decision_facility(decision_id: int, facility_id: str | None):
    if facility_id is None:
        return
    with session() as s:
        decision = s.get(Decision, decision_id)
        if not decision or decision.facility_id != facility_id:
            raise HTTPException(404, "Decision does not belong to the selected facility")


@router.get("/past-decisions")
def past_decisions(background_tasks: BackgroundTasks, snapshot_id: str | None = None, facility_id: str | None = None):
    if facility_id is not None:
        try:
            get_facility(facility_id)
        except KeyError:
            raise HTTPException(404, "unknown facility") from None
    rows, due = past.list_past(snapshot_id, facility_id)
    reference = snapshots.get(snapshot_id) if snapshot_id else None
    if reference and (reference['mode'] != 'live' or reference.get('historical_context')):
        due = []  # Historical browsing must not launch paid AI reviews.
        if reference.get('as_of'):
            rows = [row for row in rows if datetime.fromisoformat(row['decided_at']) <= datetime.fromisoformat(reference['as_of'])]
    if due:
        background_tasks.add_task(past.review_due, due[:3])
    return {"decisions": rows, "reviewing": due[:3]}


class ReviewIn(BaseModel):
    reviewer: str = Field(min_length=2, max_length=120)
    verdict: Literal["good_call", "too_lenient", "too_strict", "mixed"]
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("reviewer")
    @classmethod
    def named(cls, v: str) -> str:
        if len(v.strip()) < 2:
            raise ValueError("Reviewer name required")
        return v.strip()


@router.post("/decisions/{decision_id}/review", status_code=201)
def review_decision(decision_id: int, r: ReviewIn, facility_id: str | None = None):
    _check_decision_facility(decision_id, facility_id)
    try:
        return past.add_manager_review(decision_id, r.reviewer, r.verdict, r.note)
    except KeyError:
        raise HTTPException(404, "decision not found")


@router.post("/decisions/{decision_id}/ai-review", status_code=201)
async def ai_review_decision(decision_id: int, facility_id: str | None = None):
    _check_decision_facility(decision_id, facility_id)
    try:
        return await past.run_review(decision_id)
    except KeyError:
        raise HTTPException(404, "decision not found")
    except past.NotYet as e:
        raise HTTPException(409, str(e))
