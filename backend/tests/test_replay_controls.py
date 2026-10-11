"""Real archived quiet-weather control: provenance, cutoff, and offline API behavior."""
import gzip
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlmodel import select

from app import db, historical, replay_controls as control, snapshots
from app.config import settings
from app.models import Decision, HistoricalEvaluation, HistoryEvent, NotificationPackage, Snapshot
from app.routers import core, history

AT = datetime.fromisoformat("2024-07-18T09:00:00+00:00")


@pytest.fixture
def offline_db(tmp_path, monkeypatch):
    old = db._engine
    engine = db.make_engine(f"sqlite:///{tmp_path}/control.db")
    db.set_engine(engine)
    monkeypatch.setattr(settings, "db_path", tmp_path / "control.db")
    monkeypatch.setattr(settings, "demo_mode", True)

    def forbidden(*args, **kwargs):
        pytest.fail("The retained normal-weather control must not fetch weather or call AI")

    from ai import agent
    monkeypatch.setattr(agent, "interpret", forbidden)
    monkeypatch.setattr(snapshots, "_start_enrichment", forbidden)
    monkeypatch.setattr(historical, "year_rows", forbidden)
    monkeypatch.setattr(historical, "gather", forbidden)
    yield
    db.set_engine(old)
    engine.dispose()


def test_control_rows_are_unchanged_subset_of_checksummed_station_archive():
    source = control.fixture()["source"]
    parent = control.FIXTURE.parents[2] / "data/backtesting/datasets/objects" / source["parent_object_sha256"]
    content = parent.read_bytes()
    assert hashlib.sha256(content).hexdigest() == source["parent_object_sha256"]
    original = json.loads(gzip.decompress(content))
    by_time = {r["utc_valid"]: r for r in original["rows"]}
    assert len(source["rows"]) == 41
    assert all(row == by_time[row["utc_valid"]] for row in source["rows"])
    assert source["raw_sha256"] == original["raw_sha256"]
    observed = historical.outcome(source["rows"], "2024-07-18", "America/Chicago")
    assert observed["gradable"] and observed["disruptive"] is False
    assert observed["hours"] == observed["expected_hours"] == 24
    assert observed["freezing_precip_hours"] == observed["snow_hours"] == 0
    assert observed["max_gust_mph"] is None  # absent gust reports are not measured zeroes


def test_all_control_hours_have_no_hazard_escalation_and_missing_evidence_is_honest():
    event = control.event()
    assert event["kind"] == "normal-control" and len(event["timeline"]) == 24
    assert {p["posture"] for p in event["timeline"]} == {"NORMAL"}
    assert {p["readiness"] for p in event["timeline"]} == {"YELLOW"}
    assert {p["coverage"] for p in event["timeline"]} == {"partial"}
    for p in event["timeline"]:
        _, inputs, _, result = control.evaluation(datetime.fromisoformat(p["as_of"]))
        assert inputs and all(i.role == "observation" for i in inputs)
        assert not any(r.triggered for r in result.rules)
        assert all(h.score == 0 for h in result.hazards.values())
        assert result.readiness.decide_by is None
        assert result.sufficiency.status == "insufficient"
        assert not result.sufficiency.supports_all_clear


def test_future_observations_cannot_change_the_selected_recommendation(monkeypatch):
    _, baseline_inputs, _, baseline = control.evaluation(AT)
    data = deepcopy(control.fixture())
    for row in data["source"]["rows"]:
        if datetime.fromisoformat(row["utc_valid"]) > AT - timedelta(minutes=15):
            row.update(gust=200, feel=-100, wxcodes="FZRA SN")
    monkeypatch.setattr(control, "fixture", lambda: data)
    _, inputs, _, result = control.evaluation(AT)
    assert inputs == baseline_inputs and result == baseline
    assert historical.outcome(data["source"]["rows"], "2024-07-18", "America/Chicago")["disruptive"]


@pytest.mark.parametrize("as_of", ["2024-07-17T09:00:00+00:00", "2024-07-19T05:00:00+00:00", "2024-07-18T09:00:01+00:00"])
def test_control_rejects_times_outside_its_supported_day_or_precision(as_of):
    with pytest.raises(HTTPException) as error:
        control.evaluation(datetime.fromisoformat(as_of))
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_control_available_on_empty_install_reuses_snapshot_and_charts_are_as_of(offline_db):
    app = FastAPI()
    app.include_router(history.router)
    app.include_router(core.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        catalog = await client.get("/api/history/events")
        assert catalog.status_code == 200
        assert [e["id"] for e in catalog.json()] == [control.CONTROL_ID]
        detail = await client.get(f"/api/history/events/{control.CONTROL_ID}")
        assert detail.status_code == 200 and len(detail.json()["timeline"]) == 24
        params = {"as_of": "2024-07-18T09:17:00Z"}
        first = await client.get(f"/api/history/events/{control.CONTROL_ID}/replay", params=params)
        assert first.status_code == 200
        snap = first.json()
        again = await client.get(f"/api/history/events/{control.CONTROL_ID}/replay", params=params)
        assert again.status_code == 200
        assert snap["snapshot_id"] == again.json()["snapshot_id"]
        assert again.json()["integrity_ok"] is True
        assert snap["posture"]["posture"] == "NORMAL" and snap["readiness"]["level"] == "YELLOW"
        assert snap["sufficiency"]["supports_all_clear"] is False
        assert snap["mode"] == "backtest" and snap["model_id"] == "deterministic-fallback"
        assert snap["historical_context"]["control"]["kind"] == "normal-weather"
        assert snap["historical_context"]["outcome"]["hours"] == 24
        assert snap["historical_context"]["outcome"]["disruptive"] is False
        assert snap["alerts"] == []
        assert {s["adapter"]: s["status"] for s in snap["sources"]} == {
            "iem_obs": "ok", "iem_mos": "unavailable", "iem_vtec": "unavailable"}
        chart = await client.get("/api/timeseries", params={"snapshot_id": snap["snapshot_id"]})
        assert chart.status_code == 200
        rows = chart.json()["rows"]
        assert rows and all(datetime.fromisoformat(r["t"]) <= AT + timedelta(minutes=2) for r in rows)
        assert all("obs_temp_f" in r and "obs_wind_speed_mph" in r for r in rows)
        assert not any(k.startswith("fcst_") for r in rows for k in r)
        assert {"obs_temp_f", "obs_wind_speed_mph"}.issubset(chart.json()["meta"])
        invalid = await client.get(f"/api/history/events/{control.CONTROL_ID}/replay", params={"as_of": "2024-07-19T05:00:00Z"})
        assert invalid.status_code == 422
    with db.session() as session:
        assert len(session.exec(select(Snapshot)).all()) == 1
        for model in [HistoricalEvaluation, HistoryEvent, Decision, NotificationPackage]:
            assert session.exec(select(model)).all() == []


def test_existing_advisory_is_relabelled_without_mutating_stored_evidence():
    raw = json.loads((control.FIXTURE.parent / "advisory-2025-02-05.json").read_text())
    event = HistoryEvent(**raw["event"], verification_json=json.dumps(raw["verification"]),
                         outcome_json=json.dumps(raw["outcome"]), backtest_json=json.dumps(raw["backtest"]))
    event.name = "Feb 5, 2025 winter weather advisory (control case)"
    event.start = datetime.fromisoformat(raw["event"]["start"])
    event.end = datetime.fromisoformat(raw["event"]["end"])
    result = history._event_dict(event)
    assert "mild-weather case" in result["name"] and "control case" in event.name
    assert result["outcome"] == raw["outcome"]
