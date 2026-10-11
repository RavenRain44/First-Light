"""Gauge identity, local windows, and AI context stay grounded in the saved site."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from ai import review
from ai.tools import water_conditions
from app.facility import get_facility
from app.routers.core import build_timeseries
from engine.outcomes import grade


def record():
    return {"snapshot_id": "coastal-chart", "facility": get_facility("NC-WILMINGTON-SC").model_dump(),
            "as_of": "2024-10-17T08:00:00+00:00", "inputs": [], "signals": {}, "rules": []}


def gauge(station, value, datum="MLLW", role="forecast"):
    return {"id": f"water.{station}.{role}", "kind": "series", "role": role, "metric": "water_level_ft",
            "unit": "ft", "value": None, "source": "NOAA", "source_url": f"https://api.water.noaa.gov/{station}",
            "fetched_at": "2024-10-17T08:00:00+00:00", "source_time": "2024-10-17T07:00:00+00:00",
            "data": {"station_id": station, "datum": datum, "flood_stage_ft": 5.5},
            "series": [{"t": "2024-10-17T09:00:00+00:00", "v": value}]}


def test_gauges_do_not_overwrite_each_other_and_future_observations_are_hidden():
    snap = record()
    snap["inputs"] = [gauge("WLON7", 6.0), gauge("BEACH", 2.5, "NAVD88"), gauge("WLON7", 7.0, role="observation")]
    saved = deepcopy(snap)
    chart = build_timeseries(snap)
    assert chart["rows"][0]["fcst_water_level_ft_WLON7"] == 6.0
    assert chart["rows"][0]["fcst_water_level_ft_BEACH"] == 2.5
    assert not any("obs_water_level_ft_WLON7" in row for row in chart["rows"])
    assert chart["meta"]["fcst_water_level_ft_BEACH"]["datum"] == "NAVD88"
    assert chart["meta"]["fcst_water_level_ft_WLON7"]["provenance"]["flood_stage_ft"] == 5.5
    assert snap == saved


def test_chart_uses_recorded_hours_and_thresholds_with_a_coastal_horizon():
    snap = record()
    snap["facility"]["hours"] = {"open": "10:00", "close": "14:00"}
    snap["rules"] = [{"rule_id": "wind.fcst_gust_warning", "threshold": 91.0, "unit": "mph",
                      "verified": False, "posture_effect": "significant"}]
    at = datetime.fromisoformat(snap["as_of"]) + timedelta(hours=70)
    snap["inputs"] = [{**gauge("unused", 0), "id": "fcst.qpf_in", "metric": "qpf_in", "unit": "in",
                       "data": {}, "series": [{"t": at.isoformat(), "v": 0.2}]}]
    chart = build_timeseries(snap)
    assert chart["threshold_lines"][0]["value"] == 91.0
    hours = next(window for window in chart["windows"] if window["kind"] == "hours" and window["start"].startswith("2024-10-17"))
    assert hours["start"] == "2024-10-17T14:00:00+00:00"
    assert chart["rows"][0]["fcst_rain_in"] == 0.2


def test_water_ai_view_preserves_gauge_datum_and_regional_scope():
    snap = record()
    snap["inputs"] = [gauge("WLON7", 6.0)]
    view = water_conditions(snap)[0]
    assert view["station_id"] == "WLON7" and view["datum"] == "MLLW"
    assert view["peak_level"] == "6 ft" and "EDT" in view["peak_local"]
    assert "inundation has not been established" in view["scope"]


@pytest.mark.asyncio
async def test_incomplete_coastal_outcomes_cannot_get_a_confident_ai_grade(monkeypatch):
    outcome = {"outcome_sufficient": False, "station_peak_gust_mph": 10.0}
    check = grade("CLOSED", outcome)
    assert check["verdict"] == "mixed" and check["assessment_status"] == "insufficient"
    monkeypatch.setattr(review.settings, "model_provider", "akamai")
    monkeypatch.setattr(review.settings, "akamai_api_key", "test-key")

    async def unexpected(*args, **kwargs):
        raise AssertionError("Incomplete outcomes must not be sent to inference for a verdict")

    monkeypatch.setattr(review, "_akamai_chat", unexpected)
    result = await review.review({"observed": outcome}, check)
    assert result["source"] == "template" and result["confidence"] == 0.3
    assert "Insufficient outcome evidence" in result["note"]
