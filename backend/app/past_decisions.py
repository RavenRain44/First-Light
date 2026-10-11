"""Past manager decisions, ranked by how similar their weather was to now, with how they turned out.

Builds on what is saved when a decision is recorded: the Decision row, the immutable weather
snapshot it was made on (features, Cooper readiness, suggestion), and the DecisionContext tag
(demo mode / example). Only real decisions count: live-weather decisions made outside demo mode,
plus the clearly labelled seeded examples. Replay practice and demo-mode decisions are left out.

How a decision went comes from DecisionReview: a manager's review wins; otherwise an AI review
(ai/review.py) is written once the decision day is ``review_after_days`` old, or on request.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlmodel import select

from app import snapshots
from app.config import settings
from app.db import session
from app.facility import get_facility
from app.models import Decision, DecisionContext, DecisionReview, HistoryEvent, Snapshot
from engine.analogs import similarity
from engine.outcomes import grade, observed_outcome

RECENCY_DAYS = 180  # recency adds at most 10%: similarity always dominates
_running: set[int] = set()


class NotYet(Exception):
    """The decision day has not finished, so there is nothing to judge yet."""


def _utc(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def score(sim: float, decided_at: datetime, now: datetime) -> float:
    age = max(0.0, (now - _utc(decided_at)).total_seconds() / 86400)
    return sim * (0.9 + 0.1 * math.exp(-age / RECENCY_DAYS))


def counts(ctx: DecisionContext | None, mode: str) -> bool:
    """A real decision: a seeded example, or made on live weather outside demo mode."""
    if ctx and ctx.example:
        return True
    return mode == "live" and not (ctx and ctx.demo_mode)


def day_window(day: str, tz: str) -> tuple[datetime, datetime]:
    d = date.fromisoformat(day)
    start = datetime.combine(d, time(0), ZoneInfo(tz)).astimezone(timezone.utc)
    return start, start + timedelta(days=1)


def chosen_review(reviews: list[DecisionReview]) -> DecisionReview | None:
    by_time = sorted(reviews, key=lambda r: r.created_at, reverse=True)
    return next((r for r in by_time if r.source == "manager"), None) or (by_time[0] if by_time else None)


def review_dict(r: DecisionReview | None) -> dict | None:
    if not r:
        return None
    ev = json.loads(r.evidence_json or "{}")
    return {"source": r.source, "verdict": r.verdict, "confidence": r.confidence, "note": r.note, "reviewer": r.reviewer,
            "created_at": _utc(r.created_at).isoformat(), "observed": ev.get("summary"), "impact": ev.get("impact")}


def list_past(current_snapshot_id: str | None, facility_id: str | None = None, now: datetime | None = None) -> tuple[list[dict], list[int]]:
    """Ranked past decisions, plus the ids of unreviewed ones whose AI review is now due."""
    now = now or datetime.now(timezone.utc)
    f = get_facility(facility_id)
    current = snapshots.get(current_snapshot_id) if current_snapshot_id else None
    features = (current or {}).get("features") or {}
    with session() as s:
        rows = s.exec(select(Decision, Snapshot).join(Snapshot, Snapshot.snapshot_id == Decision.snapshot_id)
                      .where(Decision.facility_id == f.id)).all()
        ctx = {c.decision_id: c for c in s.exec(select(DecisionContext)).all()}
        reviews: dict[int, list[DecisionReview]] = {}
        for r in s.exec(select(DecisionReview)).all():
            reviews.setdefault(r.decision_id, []).append(r)
    latest: dict[str, tuple[Decision, Snapshot]] = {}
    for d, snap in rows:
        # On live weather, a decision on the very snapshot being viewed is today's own call, not a past one.
        # In a replay, the example decided at that same moment is exactly the past decision to show.
        if (snap.snapshot_id == current_snapshot_id and (current or {}).get("mode") == "live") or not counts(ctx.get(d.id), snap.mode):
            continue
        if snap.snapshot_id not in latest or d.decided_at > latest[snap.snapshot_id][0].decided_at:
            latest[snap.snapshot_id] = (d, snap)
    out, due = [], []
    for d, snap in latest.values():
        posture = json.loads(snap.posture_json)
        sim = similarity(features, json.loads(snap.features_json)) if features else 0.0
        _, day_end = day_window(posture["decision_day"], f.timezone)
        due_at = day_end + timedelta(days=settings.review_after_days)
        chosen = chosen_review(reviews.get(d.id, []))
        if chosen is None and now >= due_at:
            due.append(d.id)
        c = ctx.get(d.id)
        out.append({
            "decision_id": d.id, "snapshot_id": d.snapshot_id, "decided_by": d.decided_by,
            "decided_at": _utc(d.decided_at).isoformat(), "decision_day": posture["decision_day"],
            "decision_posture": d.decision_posture, "recommended_posture": d.recommended_posture,
            "followed_suggestion": d.agreed_with_recommendation, "override_reason": d.override_reason, "notes": d.notes,
            "readiness_level": snap.readiness_level or None, "headline": re.sub(r"\s*->\s*[A-Z_]+\.?$", ".", (posture.get("reasons") or [""])[0]),
            "similarity_pct": round(sim * 100, 1), "score": round(score(sim, d.decided_at, now), 4),
            "example": bool(c and c.example), "review": review_dict(chosen),
            "review_due_at": due_at.isoformat(), "day_over": now >= day_end,
        })
    out.sort(key=lambda x: -x["score"])
    return out, due


async def run_review(decision_id: int, now: datetime | None = None) -> dict:
    """Write an AI (or weather-check) review for one decision from what the weather did that day."""
    from ai.review import review

    now = now or datetime.now(timezone.utc)
    with session() as s:
        d = s.get(Decision, decision_id)
        if not d:
            raise KeyError(decision_id)
        c = s.get(DecisionContext, decision_id)
    snap = snapshots.get(d.snapshot_id)
    f = get_facility(d.facility_id)
    day = snap["posture"]["decision_day"]
    start, end = day_window(day, f.timezone)
    event = None
    if c and c.example and snap.get("event_id"):
        with session() as s:
            event = s.get(HistoryEvent, snap["event_id"])
    if event:
        outcome = json.loads(event.outcome_json)
    else:
        if now < end:
            raise NotYet(f"{day} has not finished yet; the review can be written after the day ends.")
        with session() as s:
            ranks = [json.loads(fj).get("road_worst_rank") for fj in s.exec(
                select(Snapshot.features_json).where(Snapshot.facility_id == f.id, Snapshot.mode == "live",
                                                     Snapshot.as_of >= start, Snapshot.as_of < end)).all()]
        outcome = await observed_outcome(f, start, end, road_ranks=ranks)
    warned = bool(snap.get("alerts")) or any(h.get("level", 0) > 0 for h in snap.get("hazards", {}).values())
    gaps = outcome.get("amw_peak_gust_mph") is None
    check = grade(d.decision_posture, outcome, warned=warned, data_gaps=gaps)
    evidence = {
        "decision": {"day": day, "chose": d.decision_posture, "suggested": d.recommended_posture,
                     "followed_suggestion": d.agreed_with_recommendation, "override_reason": d.override_reason},
        "at_decision_time": {"cooper_readiness": snap.get("readiness", {}).get("level") if snap.get("readiness") else None,
                             "alerts": [a.get("event") for a in snap.get("alerts", [])],
                             "suggestion_reasons": snap["posture"].get("reasons", [])[:3]},
        "observed": {k: outcome.get(k) for k in ("summary", "severe_impact", "lsr_count", "lsr_by_type", "max_reported_wind_mph",
                                                 "max_reported_snow_in", "max_reported_ice_in", "amw_peak_gust_mph",
                                                 "amw_freezing_precip_hours", "worst_corridor_rank")},
    }
    r = await review(evidence, check)
    row = DecisionReview(decision_id=decision_id, source=r["source"], verdict=r["verdict"], confidence=r["confidence"],
                         note=r["note"], reviewer="AI review" if r["source"] == "ai" else "Weather check",
                         created_at=now, evidence_json=json.dumps({"summary": outcome.get("summary"), "impact": check["impact"],
                                                                   "reasons": check["reasons"], "weather_check": check}, default=str))
    with session() as s:
        s.add(row); s.commit(); s.refresh(row)
    return review_dict(row)


async def review_due(ids: list[int]) -> None:
    """Background: AI-review due decisions, one at a time, never twice concurrently."""
    for i in ids:
        if i in _running:
            continue
        _running.add(i)
        try:
            with session() as s:
                if s.exec(select(DecisionReview).where(DecisionReview.decision_id == i)).first():
                    continue
            await run_review(i)
        except Exception:  # noqa: BLE001 - a failed background review simply stays "not reviewed yet"
            pass
        finally:
            _running.discard(i)


def add_manager_review(decision_id: int, reviewer: str, verdict: str, note: str | None, now: datetime | None = None) -> dict:
    with session() as s:
        if not s.get(Decision, decision_id):
            raise KeyError(decision_id)
        row = DecisionReview(decision_id=decision_id, source="manager", verdict=verdict, confidence=None,
                             note=(note or "").strip() or None, reviewer=reviewer.strip(), created_at=now or datetime.now(timezone.utc))
        s.add(row); s.commit(); s.refresh(row)
        return review_dict(row)
