"""A fresh or partially populated main database must expose the entire Ames replay library."""
import json
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from sqlmodel import select

from adapters import cache
from app import db, iowa_replay, snapshots
from app.config import settings
from app.models import Decision, HistoricalEvaluation, HistoryEvent, NotificationPackage, Snapshot
from app.routers import history

EVENTS = {
    "derecho-2020-08-10", "wind-2021-12-15", "blizzard-2022-12-22",
    "ice-2023-02-22", "snow-2024-01-09", "advisory-2025-02-05",
    "blizzard-2025-03-05", "normal-2024-07-18",
}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    old = db._engine
    engine = db.make_engine(f"sqlite:///{tmp_path}/iowa.db")
    db.set_engine(engine)
    monkeypatch.setattr(settings, "db_path", tmp_path / "iowa.db")
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "model_provider", "none")

    def forbidden(*args, **kwargs):
        pytest.fail("The curated catalog and timeline must not fetch weather or call paid AI")

    monkeypatch.setattr(cache, "_client_get", forbidden)
    monkeypatch.setattr(snapshots, "_start_enrichment", forbidden)
    yield
    db.set_engine(old)
    engine.dispose()


def app():
    instance = FastAPI()
    instance.include_router(history.router)
    return instance


@pytest.mark.asyncio
async def test_fresh_catalog_contains_all_integration_iowa_events_without_writing_records(isolated):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        for params in ({}, {"facility_id": iowa_replay.FACILITY_ID}):
            response = await client.get("/api/history/events", params=params)
            assert response.status_code == 200
            entries = response.json()
            assert len(entries) == len(EVENTS)
            assert {e["id"] for e in entries} == EVENTS
            assert all(e.get("facility_id", iowa_replay.FACILITY_ID) == iowa_replay.FACILITY_ID for e in entries)
            assert all(e["verification"] and e["outcome"] and e["backtest"] for e in entries)
    with db.session() as session:
        for model in (HistoryEvent, Snapshot, HistoricalEvaluation, Decision, NotificationPackage):
            assert session.exec(select(model)).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("event_id", sorted(EVENTS - {"normal-2024-07-18"}))
async def test_every_curated_storm_has_a_timeline_and_time_gated_report_on_a_fresh_database(isolated, event_id):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        detail = await client.get(f"/api/history/events/{event_id}")
        assert detail.status_code == 200
        event = detail.json()
        timeline = event["timeline"]
        assert 35 <= len(timeline) <= 40
        assert timeline[0]["as_of"] == event["start"] and timeline[-1]["as_of"] == event["end"]
        at = event["backtest"]["at_0400_local"]["as_of"]
        cell = next(point for point in timeline if point["as_of"] == at)
        assert cell["coverage"] != "unavailable"
        assert event["backtest"]["at_0400_local"]["posture"] == cell["posture"]
        assert event["backtest"]["at_0400_local"]["readiness"] == cell["readiness"]
        assert event["recorded_backtest"] == iowa_replay.event(event_id)["backtest"]
        # Reading the timeline must not store or enrich dozens of reports.
        with db.session() as session:
            assert session.exec(select(Snapshot)).all() == []
        response = await client.get(f"/api/history/events/{event_id}/replay", params={"as_of": at})
        assert response.status_code == 200
        report = response.json()
        assert report["facility"]["id"] == iowa_replay.FACILITY_ID
        assert report["event_id"] == event_id and report["as_of"] == at
        assert report["mode"] == "replay" and report["integrity_ok"] is True
        assert report["posture"]["posture"] == cell["posture"]
        assert report["readiness"]["level"] == cell["readiness"]
        assert report["inputs"]
        for item in report["inputs"]:
            if item["source_time"]:
                assert datetime.fromisoformat(item["source_time"]) <= datetime.fromisoformat(at)
            if item["role"] == "observation" and item["series"]:
                assert all(datetime.fromisoformat(p["t"]) <= datetime.fromisoformat(at) for p in item["series"])
    with db.session() as session:
        assert len(session.exec(select(Snapshot)).all()) == 1
        assert session.exec(select(HistoryEvent)).all() == []
        assert session.exec(select(Decision)).all() == []
        assert session.exec(select(NotificationPackage)).all() == []


@pytest.mark.asyncio
async def test_partial_database_merges_catalog_without_duplicates_and_preserves_saved_metadata(isolated):
    original = iowa_replay.event("ice-2023-02-22")
    saved = HistoryEvent(
        **{key: original[key] for key in ("id", "facility_id", "hazard", "impact_day", "summary")},
        name="Saved ice storm", start=datetime.fromisoformat(original["start"]), end=datetime.fromisoformat(original["end"]),
        verification_json=json.dumps(original["verification"]), outcome_json=json.dumps(original["outcome"]),
        backtest_json=json.dumps(original["backtest"]),
    )
    with db.session() as session:
        session.add(saved)
        session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        response = await client.get("/api/history/events")
        entries = response.json()
        assert len(entries) == len(EVENTS) and {e["id"] for e in entries} == EVENTS
        assert next(e for e in entries if e["id"] == original["id"])["name"] == "Saved ice storm"
        # Metadata alone must not result in an empty timeline.
        detail = await client.get(f"/api/history/events/{original['id']}")
        assert detail.status_code == 200 and detail.json()["timeline"]
        assert detail.json()["name"] == "Saved ice storm"
    assert iowa_replay.event(original["id"]) == original


@pytest.mark.asyncio
async def test_missing_source_cache_keeps_events_visible_and_marks_timeline_unknown(isolated, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "empty-cache")
    monkeypatch.setattr(settings, "demo_mode", False)
    previous_online = cache.historical_online.get()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        assert {e["id"] for e in (await client.get("/api/history/events")).json()} == EVENTS
        response = await client.get("/api/history/events/ice-2023-02-22")
        assert response.status_code == 200
        event = response.json()
        assert len(event["timeline"]) == 38 and event["partial"] is True
        assert all(p["coverage"] == "unavailable" and p["posture"] is None and p["readiness"] is None
                   for p in event["timeline"])
        assert "evidence unavailable" in event["backtest"]["label"]
    assert cache.historical_online.get() == previous_online
    with db.session() as session:
        assert session.exec(select(Snapshot)).all() == []


@pytest.mark.asyncio
async def test_unknown_events_and_other_facility_events_are_rejected(isolated):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        for event_id, facility in (("unknown", iowa_replay.FACILITY_ID), ("ice-2023-02-22", "NC-WILMINGTON-SC"),
                                   ("nc-florence-2018-09-14", iowa_replay.FACILITY_ID)):
            assert (await client.get(f"/api/history/events/{event_id}", params={"facility_id": facility})).status_code == 404
            assert (await client.get(f"/api/history/events/{event_id}/replay", params={
                "facility_id": facility, "as_of": "2023-02-22T10:00:00Z"})).status_code == 404
