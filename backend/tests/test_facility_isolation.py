"""Facility selection must isolate evidence, records and human-only actions."""
import asyncio
import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import select

from app import db, facility as facilities, notifications, snapshots
from app.config import settings
from app.main import app
from app.models import Decision, DecisionCameraArchive, NotificationPackage
from app.routers import core
from engine.evaluate import assess

AMES = "IA-AMES-SC"
WILMINGTON = "NC-WILMINGTON-SC"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    previous = db._engine
    engine = db.make_engine(f"sqlite:///{tmp_path / 'facilities.db'}")
    db.set_engine(engine)
    monkeypatch.setattr(settings, "model_provider", "none")
    monkeypatch.setattr(settings, "demo_mode", False)
    async def no_capture(*args, **kwargs):
        return None
    monkeypatch.setattr("app.camera_archive.capture", no_capture)
    yield TestClient(app)
    db.set_engine(previous)
    engine.dispose()


def stored(facility_id, mode="live", analogs=None):
    facility = facilities.get_facility(facility_id)
    now = datetime.now(timezone.utc)
    assessment = assess([], [], facility, now, mode, employees=[])
    snap = snapshots.build_snapshot_dict(facility, assessment, [], [], mode)
    snap.update(ai={}, model_id="deterministic-fallback", prompt_version="test")
    if analogs is not None:
        snap['analogs'] = analogs
    return snapshots.store(snap)


def test_historical_display_withholds_legacy_comparisons_without_rewriting_records(isolated):
    original = [{'event_id': 'later-storm', 'outcome_summary': 'Known only after this evaluation'}]
    record = stored(AMES, 'replay', analogs=original)
    loaded = snapshots.get(record['snapshot_id'])
    assert loaded['analogs'] == original and loaded['analogs_addon'] == []
    assert loaded['integrity_ok']


def add_decision(snap):
    with db.session() as session:
        decision = Decision(snapshot_id=snap["snapshot_id"], facility_id=snap["facility"]["id"],
                            decided_by="Synthetic manager", decision_posture="NORMAL", recommended_posture="NORMAL",
                            agreed_with_recommendation=False, override_reason="Verified local conditions manually",
                            decided_at=datetime.now(timezone.utc))
        session.add(decision)
        session.commit()
        session.refresh(decision)
        return decision.id


def test_registry_and_independent_synthetic_rosters(isolated):
    response = isolated.get("/api/facilities")
    assert response.status_code == 200
    assert {f["id"] for f in response.json()} == {AMES, WILMINGTON}
    nc = isolated.get(f"/api/facility?facility_id={WILMINGTON}").json()
    assert nc["facility"]["timezone"] == "America/New_York"
    assert nc["facility"]["asos_station"] == "ILM" and nc["facility"]["synthetic"]
    assert nc["roster"]["assigned"] == len(nc["employees"]) == 270
    ames_ids = {e["id"] for e in isolated.get("/api/facility").json()["employees"]}
    assert not ames_ids.intersection(e["id"] for e in nc["employees"])
    assert isolated.get("/api/facility?facility_id=missing").status_code == 404


def test_leave_and_dated_details_are_scoped(monkeypatch):
    base = {"essential": False, "accessibility_needs": None, "teleworking_today": False,
            "commute_corridor": "local", "workdays": [0, 1, 2, 3, 4]}
    people = [{**base, "id": "NC", "assigned_facility": WILMINGTON, "this_week_location": WILMINGTON},
              {**base, "id": "IA", "assigned_facility": AMES, "this_week_location": AMES,
               "leave": [{"start": "2026-10-12", "end": "2026-10-12", "type": "leave"}]},
              {**base, "id": "detail", "assigned_facility": AMES, "this_week_location": AMES,
               "assignments": [{"start": "2026-10-12", "end": "2026-10-12", "this_week_location": WILMINGTON}]}]
    monkeypatch.setattr(facilities, "load_employees", lambda: people)
    nc = facilities.roster_summary(facilities.get_facility(WILMINGTON), "2026-10-12")
    ia = facilities.roster_summary(facilities.get_facility(AMES), "2026-10-12")
    assert nc["expected_in_building"] == 2 and nc["detailed_in"] == 1
    assert nc["on_leave"] == 0 and ia["on_leave"] == 1


def test_latest_history_and_decisions_do_not_cross_sites(isolated):
    ia, nc = stored(AMES), stored(WILMINGTON)
    ia_decision, nc_decision = add_decision(ia), add_decision(nc)
    assert isolated.get("/api/snapshot/latest").json()["snapshot_id"] == ia["snapshot_id"]
    assert isolated.get(f"/api/snapshot/latest?facility_id={WILMINGTON}").json()["snapshot_id"] == nc["snapshot_id"]
    assert [r["snapshot_id"] for r in isolated.get(f"/api/snapshots?facility_id={WILMINGTON}").json()] == [nc["snapshot_id"]]
    assert [r["id"] for r in isolated.get("/api/decisions").json()] == [ia_decision]
    assert [r["id"] for r in isolated.get(f"/api/decisions?facility_id={WILMINGTON}").json()] == [nc_decision]


def test_snapshot_and_decision_scope_mismatch_is_rejected(isolated):
    snap = stored(AMES)
    sid = snap["snapshot_id"]
    for path in (f"/api/snapshot/{sid}", f"/api/timeseries?snapshot_id={sid}", f"/api/record/{sid}"):
        separator = "&" if "?" in path else "?"
        assert isolated.get(path + separator + f"facility_id={WILMINGTON}").status_code == 404
    body = {"snapshot_id": sid, "facility_id": WILMINGTON, "decided_by": "Synthetic manager",
            "decision_posture": "NORMAL", "override_reason": "Checked conditions"}
    assert isolated.post("/api/decisions", json=body).status_code == 404
    with db.session() as session:
        assert session.exec(select(Decision)).all() == []


@pytest.mark.parametrize("mode", ["replay", "backtest", "livecheck"])
def test_historical_and_hypothetical_decisions_have_no_side_effects(isolated, mode):
    snap = stored(WILMINGTON, mode)
    response = isolated.post("/api/decisions", json={"snapshot_id": snap["snapshot_id"], "decided_by": "Synthetic manager",
                              "decision_posture": "NORMAL", "override_reason": "This is only a replay"})
    assert response.status_code == 422 and "read-only" in response.json()["detail"]
    with db.session() as session:
        assert not session.exec(select(Decision)).all()
        assert not session.exec(select(DecisionCameraArchive)).all()
        assert not session.exec(select(NotificationPackage)).all()


def test_past_decisions_infer_the_snapshot_facility(isolated):
    from app import past_decisions
    ia, nc = stored(AMES), stored(WILMINGTON)
    add_decision(ia)
    nc_decision = add_decision(nc)
    # The currently viewed snapshot's own decision is excluded; a site-scoped blank
    # reference still includes only that site's recorded calls.
    rows, _ = past_decisions.list_past(None, WILMINGTON)
    assert [r["decision_id"] for r in rows] == [nc_decision]
    assert past_decisions.list_past(nc["snapshot_id"])[0] == []
    assert isolated.get(f"/api/past-decisions?snapshot_id={nc['snapshot_id']}&facility_id={AMES}").status_code == 404


def test_notifications_are_scoped_and_replay_cannot_create_a_draft(isolated, monkeypatch):
    ids = [add_decision(stored(facility_id)) for facility_id in (AMES, WILMINGTON)]
    with db.session() as session:
        for index, facility_id in enumerate((AMES, WILMINGTON), 1):
            session.add(NotificationPackage(id=f"package-{index}", decision_id=ids[index-1], facility_id=facility_id,
                        decision_day="2026-10-12", state_json=json.dumps({"id": f"package-{index}", "facility_id": facility_id,
                        "decision_id": index, "groups": [], "version": 1})))
        session.commit()
    assert [p["facility_id"] for p in isolated.get("/api/notifications").json()["packages"]] == [AMES]
    assert [p["facility_id"] for p in isolated.get(f"/api/notifications?facility_id={WILMINGTON}").json()["packages"]] == [WILMINGTON]
    rejected = isolated.post(f"/api/notifications/packages/package-1/send?facility_id={WILMINGTON}",
                             json={"actor": "Synthetic manager", "version": 1})
    assert rejected.status_code == 404
    snap = stored(WILMINGTON, "replay")
    did = add_decision(snap)  # Retained legacy replay records cannot launch new drafts.
    with pytest.raises(HTTPException) as error:
        asyncio.run(notifications.create(did))
    assert error.value.status_code == 422


def test_nc_historical_roads_and_cameras_do_not_substitute_live_or_iowa_data(isolated, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Iowa provider must not be called for Wilmington")
    monkeypatch.setattr(core, "fetch_road_geojson", forbidden)
    when = "2024-09-16T08:00:00Z"
    roads = isolated.get(f"/api/roads?facility_id={WILMINGTON}&as_of={when}")
    cameras = isolated.get(f"/api/cameras?facility_id={WILMINGTON}&as_of={when}")
    assert roads.status_code == cameras.status_code == 200
    assert roads.json()["status"] == cameras.json()["status"] == "unavailable"
    assert not roads.json()["geojson"]["features"] and not cameras.json()["cameras"]


def test_facilities_have_independent_live_evaluation_locks():
    assert core._live_lock_for(AMES) is core._live_lock_for(AMES)
    assert core._live_lock_for(AMES) is not core._live_lock_for(WILMINGTON)


def test_live_evaluation_cannot_be_used_to_record_a_selected_historical_time(isolated):
    response = isolated.post("/api/evaluate", json={"facility_id": WILMINGTON,
                             "mode": "live", "as_of": "2024-09-16T08:00:00Z"})
    assert response.status_code == 422 and "read-only replay" in response.json()["detail"]


def test_parallel_demo_evaluations_have_separate_reference_clocks(isolated, monkeypatch):
    from adapters.base import reference_now
    monkeypatch.setattr(settings, "demo_mode", True)
    original_global = datetime(2000, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(settings, "demo_reference_now", original_global)
    observed = {}
    async def gather(facility, as_of, mode):
        await asyncio.sleep(0)
        observed[facility.id] = reference_now()
        return [], []
    monkeypatch.setattr(snapshots, "gather", gather)
    times = {AMES: datetime(2023, 2, 22, 10, tzinfo=timezone.utc),
             WILMINGTON: datetime(2024, 9, 16, 8, tzinfo=timezone.utc)}
    async def evaluate():
        return await asyncio.gather(*(snapshots.evaluate(facilities.get_facility(site), when, "live",
                                                         use_ai=False, persist=False) for site, when in times.items()))
    asyncio.run(evaluate())
    assert observed == times and settings.demo_reference_now == original_global


def test_retained_replay_packages_cannot_be_sent_or_processed(isolated):
    snap = stored(WILMINGTON, "replay")
    did = add_decision(snap)
    with db.session() as session:
        session.add(NotificationPackage(id="historical-package", decision_id=did, facility_id=WILMINGTON,
                    decision_day="2024-09-16", state_json=json.dumps({"id": "historical-package", "status": "draft",
                    "facility_id": WILMINGTON, "decision_id": did, "groups": [], "messages": [], "version": 1})))
        session.commit()
    response = isolated.post("/api/notifications/packages/historical-package/send",
                             json={"actor": "Synthetic manager", "version": 1})
    assert response.status_code == 422 and "read-only" in response.json()["detail"]
    notifications.tick()
    with db.session() as session:
        state = json.loads(session.get(NotificationPackage, "historical-package").state_json)
    assert state["status"] == "draft" and state["messages"] == []
