"""End-to-end: the August 10, 2020 derecho at 16:00 UTC (11:00 CDT), offline.

The fixture holds every normalized input the replay adapters produced for that
moment (IEM VTEC archive, archived NBM forecast, AMW ASOS, SPC outlook, RWIS).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from adapters.base import NormalizedInput, SourceStatus
from app.config import settings
from app.facility import load_facility
from engine.evaluate import assess

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "derecho_2020-08-10T16Z_inputs.json"
AS_OF = datetime(2020, 8, 10, 16, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def result():
    d = json.loads(FIX.read_text(encoding="utf-8"))
    inputs = [NormalizedInput(**i) for i in d["inputs"]]
    statuses = [SourceStatus(**s) for s in d["statuses"]]
    return assess(inputs, statuses, load_facility(), AS_OF, "replay")


def test_derecho_recommends_early_dismissal_with_shelter_guidance(result):
    assert result.posture.posture == "EARLY_DISMISSAL"
    assert result.posture.decision_day.isoformat() == "2020-08-10"
    assert any("shelter" in g.lower() for g in result.posture.guidance)
    assert result.posture.contributing_hazards == ["wind"]


def test_derecho_triggers_the_severe_thunderstorm_warning_rule_with_provenance(result):
    r = next(r for r in result.rules if r.rule_id == "wind.severe_tstorm_warning")
    assert r.triggered and r.verified
    assert r.input_ids and r.input_ids[0].startswith("alert:DMX.SV.W")
    assert r.window_start <= AS_OF <= r.window_end
    assert result.hazards["wind"].level == 2
    assert result.hazards["winter"].level == 0


def test_derecho_confidence_notes_forecast_missed_the_wind(result):
    agree = next(f for f in result.confidence.factors if f.name == "agreement")
    assert agree.score < 1.0 and "weaker than warning" in agree.explanation


def test_full_pipeline_from_committed_cache(tmp_path, monkeypatch):
    """Same moment through gather -> assess -> snapshot, served from fixtures/http_cache (DEMO_MODE)."""
    import asyncio

    from app import db, snapshots
    monkeypatch.setattr(settings, "demo_mode", True)
    old = db._engine
    db.set_engine(db.make_engine(f"sqlite:///{(tmp_path / 'e2e.db').as_posix()}"))
    try:
        snap = asyncio.run(snapshots.evaluate(load_facility(), AS_OF, "replay", use_ai=False))
    finally:
        db.set_engine(old)
    assert snap["posture"]["posture"] == "EARLY_DISMISSAL"
    assert snap["model_id"] == "deterministic-fallback"
    assert "Severe Thunderstorm Warning" in snap["ai"]["rationale_paragraph"]
    assert {s["adapter"]: s["status"] for s in snap["sources"]}["iem_vtec"] == "ok"
