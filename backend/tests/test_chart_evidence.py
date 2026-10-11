"""Charts faithfully project saved blizzard/cold evidence without modifying records."""
import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

from app import snapshots
from app.routers.core import build_timeseries
from engine.features import wind_chill_f

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/blizzard_2022-12-22T18Z_chart.json"


def test_blizzard_chart_reproduces_the_recorded_wind_chill_from_original_inputs():
    snap = json.loads(FIXTURE.read_text())["snapshot"]
    original = deepcopy(snap)
    assert snapshots.content_hash(snap) == snap["content_sha256"]
    chart = build_timeseries(snap)
    peak = snap["signals"]["fcst_min_apparent_24h_f"]
    at_peak = next(r for r in chart["rows"] if datetime.fromisoformat(r["t"]) == datetime.fromisoformat(peak["peak_time"].replace("Z", "+00:00")))
    assert at_peak["fcst_apparent_temp_f"] == peak["value"] == -36.8
    as_of = datetime.fromisoformat(snap["as_of"])
    decision_rows = [r for r in chart["rows"] if as_of <= datetime.fromisoformat(r["t"]) < as_of + timedelta(hours=24)]
    assert min(r["fcst_apparent_temp_f"] for r in decision_rows if "fcst_apparent_temp_f" in r) == peak["value"]
    assert sum(r.get("fcst_snow_in", 0) for r in decision_rows) == 0
    assert any(r.get("obs_apparent_temp_f", 0) < -35 for r in chart["rows"])
    assert chart["meta"]["fcst_apparent_temp_f"]["derived"] is True
    assert chart["meta"]["fcst_apparent_temp_f"]["input_ids"] == peak["input_ids"]
    assert snap == original and snapshots.content_hash(snap) == snap["content_sha256"]


def test_provided_feels_like_values_are_preserved_instead_of_recalculated():
    snap = json.loads(FIXTURE.read_text())["snapshot"]
    t = snap["as_of"]
    source = next(i for i in snap["inputs"] if i["id"] == "fcst.temp_f")
    snap["inputs"].append({**source, "id": "fcst.apparent_temp_f", "metric": "apparent_temp_f", "series": [{"t": t, "v": -20.0}]})
    chart = build_timeseries(snap)
    assert next(r for r in chart["rows"] if r["t"] == t)["fcst_apparent_temp_f"] == -20
    assert "derived" not in chart["meta"]["fcst_apparent_temp_f"]


def test_unrecorded_derived_evidence_is_not_added_to_an_old_snapshot():
    snap = json.loads(FIXTURE.read_text())["snapshot"]
    snap["signals"].pop("fcst_min_apparent_24h_f")
    chart = build_timeseries(snap)
    assert not any("fcst_apparent_temp_f" in r for r in chart["rows"])


def test_missing_wind_uses_the_same_fallback_as_the_recorded_engine_signal():
    snap = json.loads(FIXTURE.read_text())["snapshot"]
    snap["inputs"] = [i for i in snap["inputs"] if i["id"] != "fcst.wind_speed_mph"]
    chart = build_timeseries(snap)
    for row in chart["rows"]:
        if "fcst_apparent_temp_f" in row:
            assert row["fcst_apparent_temp_f"] == round(wind_chill_f(row["fcst_temp_f"], 0), 1)
