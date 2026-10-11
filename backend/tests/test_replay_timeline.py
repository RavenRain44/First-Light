"""Custom replay ribbons must use the selected instant and never pay for AI cells."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from adapters.base import NormalizedInput, SourceStatus
from app import replay_timeline, snapshots
from app.config import settings
from app.facility import load_facility
from app.routers import history

AS_OF = datetime(2020, 8, 10, 16, 17, tzinfo=timezone.utc)
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "derecho_2020-08-10T16Z_inputs.json"


@pytest.fixture
def evidence():
    data = json.loads(FIXTURE.read_text())
    return [NormalizedInput(**i) for i in data["inputs"]], [SourceStatus(**s) for s in data["statuses"]]


@pytest.mark.asyncio
async def test_timeline_is_bounded_centered_on_exact_minute_and_uses_real_rules(monkeypatch, evidence):
    from ai import agent

    active = peak = 0

    async def gather(facility, at, mode):
        nonlocal active, peak
        assert mode == "replay"
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return evidence

    def forbidden(*args, **kwargs):
        pytest.fail("Timeline cells must not store snapshots or call AI")

    monkeypatch.setattr(replay_timeline, "gather", gather)
    monkeypatch.setattr(snapshots, "store", forbidden)
    monkeypatch.setattr(snapshots, "_start_enrichment", forbidden)
    monkeypatch.setattr(agent, "interpret", forbidden)
    result = await replay_timeline.build_timeline(load_facility(), AS_OF)
    points = result["timeline"]
    assert len(points) == 25
    assert peak <= 3
    assert result["timezone"] == "America/Chicago"
    assert result["selected_index"] == 12
    assert [datetime.fromisoformat(p["as_of"]) for p in points] == [AS_OF + timedelta(hours=h) for h in range(-12, 13)]
    assert points[12]["posture"] == "EARLY_DISMISSAL"
    assert points[12]["readiness"] == "RED"


@pytest.mark.asyncio
async def test_missing_evidence_has_no_invented_posture_or_cooper_color(monkeypatch, evidence):
    unavailable = SourceStatus(adapter="forecast", label="Archived forecast", status="unavailable")

    async def gather(facility, at, mode):
        if at < AS_OF:
            return [], [unavailable]
        return evidence[0], [*evidence[1], unavailable]

    monkeypatch.setattr(replay_timeline, "gather", gather)
    points = (await replay_timeline.build_timeline(load_facility(), AS_OF))["timeline"]
    assert all(p["coverage"] == "unavailable" and p["posture"] is None and p["readiness"] is None for p in points[:12])
    assert points[12]["coverage"] == "partial"
    assert "Archived forecast" in points[12]["unavailable_sources"]
    assert points[12]["posture"] == "EARLY_DISMISSAL"
    assert points[12]["readiness"] == "RED"


@pytest.mark.asyncio
@pytest.mark.parametrize("as_of,expected", [
    ("2020-08-10T16:00:00Z", "EARLY_DISMISSAL"),
    ("2023-02-22T11:00:00Z", "CLOSED"),
    ("2017-06-14T16:17:00Z", None),
])
async def test_endpoint_with_committed_offline_data(monkeypatch, as_of, expected):
    monkeypatch.setattr(settings, "demo_mode", True)
    app = FastAPI()
    app.include_router(history.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/replay/timeline", params={"as_of": as_of})
    assert response.status_code == 200
    result = response.json()
    assert len(result["timeline"]) == 25
    center = result["timeline"][result["selected_index"]]
    assert datetime.fromisoformat(center["as_of"]) == datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    assert center["posture"] == expected
    if expected is None:
        assert center["coverage"] == "unavailable"
        assert center["readiness"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("as_of", ["not-a-date", "0001-01-01T00:00:00Z", "9999-12-31T23:00:00Z"])
async def test_endpoint_rejects_invalid_or_overflowing_window(as_of):
    app = FastAPI()
    app.include_router(history.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/replay/timeline", params={"as_of": as_of})
    assert response.status_code == 422
