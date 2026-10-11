"""Past decisions: which decisions count, similarity ranking with a small recency bias, reviews, grading."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app import db, past_decisions as past
from app.facility import load_facility
from app.models import Decision, DecisionContext, DecisionReview, Snapshot
from engine.outcomes import grade

FAC = load_facility()
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
STORM = {"winter_level": 3, "winter_alert_level": 3, "fcst_ice_in": 0.3, "road_worst_rank": 3}
CALM: dict = {}
SNAPS: dict[str, dict] = {}


def add_snapshot(sid, mode, features, day, level="WHITE", as_of=None, alerts=()):
    as_of = as_of or datetime.fromisoformat(f"{day}T10:00:00+00:00")
    posture = {"posture": "NORMAL", "decision_day": day, "reasons": [f"reason for {sid}"]}
    SNAPS[sid] = {"snapshot_id": sid, "mode": mode, "features": features, "posture": posture, "alerts": list(alerts),
                  "hazards": {}, "readiness": {"level": level}, "event_id": None}
    values = {f: "{}" for f in Snapshot.model_fields if f.endswith("_json")}
    values.update(features_json=json.dumps(features), posture_json=json.dumps(posture))
    with db.session() as s:
        s.add(Snapshot(**values, snapshot_id=sid, facility_id=FAC.id, as_of=as_of, created_at=as_of,
                       mode=mode, posture="NORMAL", opm_label="Open", confidence="high", confidence_score=1, readiness_level=level,
                       thresholds_version="v1", thresholds_sha256="h", model_id="none", prompt_version="v1", content_sha256="h"))
        s.commit()


def add_decision(sid, posture="NORMAL", at=None, demo=False, example=False, context=True):
    at = at or datetime.fromisoformat(SNAPS[sid]["posture"]["decision_day"] + "T10:00:00+00:00")
    with db.session() as s:
        d = Decision(snapshot_id=sid, facility_id=FAC.id, decided_by="Pat", decision_posture=posture, recommended_posture="NORMAL",
                     agreed_with_recommendation=posture == "NORMAL", override_reason=None if posture == "NORMAL" else "why",
                     decided_at=at if at.tzinfo else at.replace(tzinfo=timezone.utc))
        s.add(d); s.commit(); s.refresh(d)
        if context:
            s.add(DecisionContext(decision_id=d.id, demo_mode=demo, example=example)); s.commit()
        return d.id


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    old = db._engine
    engine = db.make_engine(f"sqlite:///{tmp_path / 'past.db'}")
    db.set_engine(engine)
    SNAPS.clear()
    monkeypatch.setattr(past.snapshots, "get", lambda sid: SNAPS.get(sid))
    monkeypatch.setattr(past.settings, "model_provider", "none")  # AI off: reviews use the weather check
    yield
    db.set_engine(old)
    engine.dispose()


def test_only_real_decisions_count():
    add_snapshot("now", "live", STORM, "2026-10-20")
    add_snapshot("live", "live", STORM, "2026-01-05"); real = add_decision("live")
    add_snapshot("legacy", "live", STORM, "2026-01-06"); legacy = add_decision("legacy", context=False)  # before tagging existed
    add_snapshot("demo", "live", STORM, "2026-01-07"); add_decision("demo", demo=True)
    add_snapshot("practice", "replay", STORM, "2023-02-22"); add_decision("practice")
    add_snapshot("example", "replay", STORM, "2023-02-23"); ex = add_decision("example", example=True)
    add_decision("now")  # the decision on the current snapshot is not a "past" one
    rows, _ = past.list_past("now", now=NOW)
    assert {r["decision_id"] for r in rows} == {real, legacy, ex}
    assert next(r for r in rows if r["decision_id"] == ex)["example"] is True


def test_latest_decision_per_snapshot():
    add_snapshot("now", "live", CALM, "2026-10-20")
    add_snapshot("a", "live", CALM, "2026-01-05")
    add_decision("a", at=datetime(2026, 1, 5, 9))
    later = add_decision("a", posture="TELEWORK", at=datetime(2026, 1, 5, 11))
    rows, _ = past.list_past("now", now=NOW)
    assert [r["decision_id"] for r in rows] == [later]


def test_similarity_dominates_recency_bias_is_small():
    add_snapshot("now", "live", STORM, "2026-10-20")
    add_snapshot("old_storm", "live", STORM, "2022-12-22"); old_storm = add_decision("old_storm")
    add_snapshot("new_calm", "live", CALM, "2026-10-15"); add_decision("new_calm")
    add_snapshot("new_storm", "live", STORM, "2026-10-01"); new_storm = add_decision("new_storm")
    rows, _ = past.list_past("now", now=NOW)
    assert [r["decision_id"] for r in rows][:2] == [new_storm, old_storm]  # equal similarity: newer first
    assert rows[-1]["similarity_pct"] < rows[0]["similarity_pct"]          # the calm day ranks last despite being newest
    assert past.score(1.0, NOW - timedelta(days=3650), NOW) >= 0.9          # at most a 10% recency effect


def test_manager_review_beats_ai_and_reviews_are_append_only(monkeypatch):
    add_snapshot("now", "live", CALM, "2026-10-20")
    add_snapshot("a", "live", CALM, "2026-09-01"); d = add_decision("a", posture="CLOSED")
    monkeypatch.setattr(past, "observed_outcome", calm_day)
    asyncio.run(past.run_review(d, now=NOW))
    rows, _ = past.list_past("now", now=NOW)
    assert rows[0]["review"]["source"] == "template" and rows[0]["review"]["verdict"] == "too_strict"
    past.add_manager_review(d, "Pat", "good_call", "Power was out at the building.", now=NOW)
    rows, _ = past.list_past("now", now=NOW)
    assert rows[0]["review"]["source"] == "manager" and rows[0]["review"]["verdict"] == "good_call"
    with db.session() as s, pytest.raises(IntegrityError):
        r = s.get(DecisionReview, 1); r.verdict = "mixed"; s.add(r); s.commit()


async def calm_day(*_a, **_k):
    return {"summary": "no storm reports within 25 mi; AMW peak gust 18 mph.", "severe_impact": False, "lsr_count": 0,
            "coverage": {"complete": True, "observed_hours": 24, "expected_hours": 24},
            "lsr_by_type": {}, "lsrs": [], "amw_peak_gust_mph": 18.0, "amw_freezing_precip_hours": 0, "worst_corridor_rank": 0}


def test_review_due_after_seven_days_and_not_before_day_ends():
    add_snapshot("now", "live", CALM, "2026-10-20")
    add_snapshot("old", "live", CALM, "2026-10-01"); old = add_decision("old")
    add_snapshot("recent", "live", CALM, "2026-10-18"); add_decision("recent")
    add_snapshot("today", "live", CALM, "2026-10-21"); today = add_decision("today")
    _, due = past.list_past("now", now=NOW)
    assert due == [old]
    with pytest.raises(past.NotYet):
        asyncio.run(past.run_review(today, now=NOW))


def outcome(**k):
    base = {"severe_impact": False, "lsr_count": 0, "lsr_by_type": {}, "lsrs": [], "amw_peak_gust_mph": 20, "amw_freezing_precip_hours": 0,
            "worst_corridor_rank": 0, "max_reported_wind_mph": None, "max_reported_snow_in": None, "max_reported_ice_in": None}
    return {**base, **k}


def test_grade_tornado_and_forming_weather():
    tornado = outcome(severe_impact=True, lsr_count=2, lsr_by_type={"TORNADO": 1, "TSTM WND DMG": 1})
    assert grade("CLOSED", tornado)["verdict"] == "good_call"
    assert grade("NORMAL", tornado)["verdict"] == "too_lenient"
    # Closed for a tornado threat that never formed: defensible, not clear-cut.
    quiet = outcome()
    assert grade("CLOSED", quiet, warned=True)["verdict"] == "mixed"
    assert grade("CLOSED", quiet)["verdict"] == "too_strict"
    assert grade("NORMAL", quiet)["verdict"] == "good_call"
    snowed_in = outcome(severe_impact=True, lsr_count=37, lsr_by_type={"SNOW": 37}, max_reported_snow_in=10.2, worst_corridor_rank=3)
    assert grade("DELAYED_ARRIVAL", snowed_in)["verdict"] == "too_lenient"
    assert grade("NORMAL", quiet, data_gaps=True)["confidence"] < grade("NORMAL", quiet)["confidence"]


def test_record_decision_tags_demo_mode(monkeypatch):
    from app.main import app
    from app.routers import core
    add_snapshot("s", "live", CALM, "2026-10-20")
    SNAPS["s"]["facility"] = {"id": FAC.id}
    SNAPS["s"]["sufficiency"] = {"status": "sufficient", "reason_required": False, "supports_all_clear": True}
    monkeypatch.setattr(core.snapshots, "get", lambda sid: SNAPS.get(sid))
    monkeypatch.setattr(core.settings, "demo_mode", True)
    import app.camera_archive as ca
    async def no_capture(*a, **k): return None
    monkeypatch.setattr(ca, "capture", no_capture)
    r = TestClient(app).post("/api/decisions", json={"snapshot_id": "s", "decided_by": "Pat Lee", "decision_posture": "NORMAL", "intended_objective": "Protect commuters"})
    assert r.status_code == 201
    with db.session() as s:
        assert s.get(DecisionContext, r.json()["id"]).demo_mode is True
        from app.models import DecisionIntent
        from sqlmodel import select
        objective = s.exec(select(DecisionIntent)).one()
        assert objective.objective == "Protect commuters" and objective.retrospective is False
        assert r.json()["decided_at"].endswith("+00:00")


def test_replay_shows_the_example_decided_at_that_same_moment():
    add_snapshot("ice", "replay", STORM, "2023-02-22", level="RED"); ex = add_decision("ice", posture="CLOSED", example=True)
    rows, _ = past.list_past("ice", now=NOW)
    assert rows[0]["decision_id"] == ex and rows[0]["similarity_pct"] == 100.0
