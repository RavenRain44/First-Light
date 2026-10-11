"""Analog matching: normalization, similarity ordering, quiet-day guard."""
from engine import analogs

ICE = {"winter_alert_level": 3, "winter_level": 3, "fcst_ice_in": 0.3, "road_worst_rank": 3, "obs_freezing_hours": 2,
       "min_apparent_f": 20, "spc_rank": -1, "hours_to_peak": 3}
WIND = {"wind_alert_level": 2, "wind_level": 2, "max_gust_mph": 70, "spc_rank": 4, "min_apparent_f": 80, "hours_to_peak": 1}
QUIET = {"min_apparent_f": 60, "spc_rank": -1, "hours_to_peak": 48}


def test_identical_vectors_are_100_percent():
    assert analogs.similarity(ICE, ICE) == 1.0


def test_similar_beats_dissimilar():
    light_ice = {**ICE, "fcst_ice_in": 0.15, "winter_alert_level": 2, "winter_level": 2}
    assert analogs.similarity(ICE, light_ice) > analogs.similarity(ICE, WIND)
    assert 0.0 <= analogs.similarity(ICE, WIND) < 0.8


def test_normalization_clips_to_unit_range():
    n = analogs.normalize({"max_gust_mph": 200, "fcst_ice_in": -1})
    assert n["max_gust_mph"] == 1.0 and n["fcst_ice_in"] == 0.0


def test_quiet_day_returns_no_analogs():
    assert analogs.find_analogs(QUIET) == []


def test_strict_replay_does_not_consult_retrospective_outcome_library(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Historical outcome publication times are not verified")
    monkeypatch.setattr(analogs, "_library", forbidden)
    for mode in ("replay", "backtest"):
        assert analogs.find_analogs(ICE, mode=mode) == []


def test_find_analogs_ranks_library(monkeypatch):
    from datetime import datetime
    lib = [
        {"event_id": "ice", "name": "Ice", "hazard": "winter", "as_of": datetime(2023, 2, 22, 11), "posture": "CLOSED",
         "features": ICE, "outcome": {"summary": "ice"}},
        {"event_id": "wind", "name": "Wind", "hazard": "wind", "as_of": datetime(2020, 8, 10, 16), "posture": "EARLY_DISMISSAL",
         "features": WIND, "outcome": {"summary": "wind"}},
        {"event_id": "wind", "name": "Wind", "hazard": "wind", "as_of": datetime(2020, 8, 10, 3), "posture": "NORMAL",
         "features": QUIET, "outcome": {"summary": "wind"}},
    ]
    monkeypatch.setattr(analogs, "_library", lambda stamp=0: lib)
    res = analogs.find_analogs({**ICE, "fcst_ice_in": 0.2})
    assert [r["event_id"] for r in res] == ["ice", "wind"]
    assert res[0]["label"] == "simulated by rules (backtest)" and res[0]["similarity_pct"] > res[1]["similarity_pct"]
    assert analogs.find_analogs(ICE, exclude_event="ice")[0]["event_id"] == "wind"
