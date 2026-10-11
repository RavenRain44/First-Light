"""Manager review, simulation outbox, and demo clock endpoints."""
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlmodel import select

from app import notifications as n
from app.db import session
from app.models import NotificationAudit, NotificationClock, NotificationPackage

router = APIRouter(prefix="/api/notifications")


class Create(BaseModel):
    decision_id: int
    fallback_start: str | None = None
    include_unchanged: bool = False


class Action(BaseModel):
    version: int
    actor: str = Field(min_length=2, max_length=120)

    @field_validator("actor")
    @classmethod
    def actor_required(cls, value):
        if len(value.strip()) < 2:
            raise ValueError("Manager name required")
        return value.strip()


class Edit(Action):
    location_text: str | None = Field(default=None, min_length=1, max_length=300)
    decision_text: str | None = Field(default=None, min_length=1, max_length=1000)
    instruction_text: str | None = Field(default=None, min_length=1, max_length=1000)
    sms_intro: str = Field(max_length=120)
    email_intro: str = Field(max_length=2000)
    schedule_override: datetime | None = None
    scenario: Literal["success", "failure", "delay"] = "success"
    test_contacts: list[str] = Field(default_factory=list)
    recipient_ids: list[str] | None = None

    @field_validator("schedule_override")
    @classmethod
    def aware_schedule(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Include a UTC offset in the delivery timestamp")
        return value


class Clock(BaseModel):
    now: datetime | None = None
    actor: str = Field(min_length=2, max_length=120)

    @field_validator("now")
    @classmethod
    def aware_clock(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Include a UTC offset in the demo timestamp")
        return value


@router.get("")
def overview():
    with session() as s:
        clock = s.get(NotificationClock, 1)
        packages = [json.loads(r.state_json) for r in s.exec(select(NotificationPackage)).all()]
        for p in packages:
            for g in p["groups"]:
                g["previews"] = {c: n.message_text(p, g, c, "Recipient") for c in ("sms", "email")}
        return {"provider": "simulation", "now": n.clock_now(s).isoformat(),
                "demo_clock": bool(clock and clock.simulated_now), "contacts": n.contacts(),
                "packages": sorted(packages, key=lambda p: p["decision_id"], reverse=True)}


@router.post("/packages")
async def create(req: Create):
    return await n.create(req.decision_id, req.fallback_start, req.include_unchanged)


@router.put("/packages/{pid}/groups/{gid}")
def edit(pid: str, gid: str, req: Edit):
    return n.edit(pid, gid, req)


@router.post("/packages/{pid}/groups/{gid}/approve")
def approve(pid: str, gid: str, req: Action):
    return n.approve(pid, gid, req)


@router.post("/packages/{pid}/send")
def send(pid: str, req: Action):
    return n.dispatch(pid, req)


@router.post("/packages/{pid}/messages/{mid}/retry")
def retry(pid: str, mid: str, req: Action):
    return n.retry(pid, mid, req)


@router.put("/clock")
def clock(req: Clock):
    n.set_clock(req.now, req.actor)
    return {"ok": True}


@router.get("/packages/{pid}/audit")
def audit(pid: str):
    with session() as s:
        return [r.model_dump(mode="json") for r in s.exec(select(NotificationAudit)
                .where(NotificationAudit.package_id == pid).order_by(NotificationAudit.id)).all()]


@router.post("/packages/{pid}/followup")
def followup(pid: str, req: Action):
    return n.followup(pid, req)


class GroupReview(BaseModel):
    id: str
    location_text: str | None = Field(default=None, min_length=1, max_length=300)
    decision_text: str | None = Field(default=None, min_length=1, max_length=1000)
    instruction_text: str | None = Field(default=None, min_length=1, max_length=1000)
    sms_intro: str = Field(max_length=120)
    email_intro: str = Field(max_length=2000)
    recipient_ids: list[str]
    test_contacts: list[str] = Field(default_factory=list)
    schedule_override: datetime | None = None
    scenario: Literal["success", "failure", "delay"] = "success"


class Review(Action):
    groups: list[GroupReview]
    approve_and_send: bool = False


@router.post("/packages/{pid}/review")
def review(pid: str, req: Review):
    with session() as s:
        _, p = n.require_package(s, pid, req.version)
    if {g.id for g in req.groups} != {g["id"] for g in p["groups"]} or len(req.groups) != len(p["groups"]):
        raise HTTPException(422, "Review must include every group exactly once")
    try:
        prepared = [(group.id, Edit(**{k: v for k, v in group.model_dump().items() if k != "id"},
                                   version=p["version"], actor=req.actor)) for group in req.groups]
    except ValidationError:
        raise HTTPException(422, "Check draft lengths and include a UTC offset in scheduling overrides")
    for gid, data in prepared:
        data.version = p["version"]
        p = n.edit(pid, gid, data)
        if req.approve_and_send:
            p = n.approve(pid, gid, Action(version=p["version"], actor=req.actor))
    return n.dispatch(pid, Action(version=p["version"], actor=req.actor)) if req.approve_and_send else p


class RealTest(Action):
    group_id: str
    contact_ids: list[str]
    request_id: str = Field(min_length=8, max_length=100)


@router.get("/delivery-setup")
def delivery_setup():
    from app.real_delivery import readiness
    return readiness()


@router.post("/delivery-setup/check")
def check_smtp_connection():
    from app.smtp_service import check_connection
    return check_connection()


@router.post("/packages/{pid}/real-test")
def real_test(pid: str, req: RealTest):
    from app.real_delivery import send_tests
    return send_tests(pid, req)


@router.post("/packages/{pid}/regenerate")
async def regenerate(pid: str, req: Action):
    return await n.regenerate(pid, req)
