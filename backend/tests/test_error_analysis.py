"""Errors & risk trade-offs: error-rate denominators, small/single-class samples, costs, threshold
trade-offs, separation of weather labels from operating decisions, and the read-only action view."""
import json

from fastapi.testclient import TestClient
from sqlmodel import select

from app import db
from app.facility import load_employees
from app.models import Decision, DecisionContext
from engine import error_analysis as ea
from engine.action_risk import assess_actions
from engine.scoring import load_thresholds


def pairs(tp=0, fp=0, tn=0, fn=0):
    return [(True, True)] * tp + [(True, False)] * fp + [(False, False)] * tn + [(False, True)] * fn


def test_denominators_and_precision_are_different():
    r = ea.rates(pairs(tp=30, fp=10, tn=90, fn=20))
    assert r["false_positive_rate"]["n"] == 100 and r["false_positive_rate"]["rate"] == 0.1   # FP/(FP+TN)
    assert r["false_negative_rate"]["n"] == 50 and r["false_negative_rate"]["rate"] == 0.4    # FN/(FN+TP)
    recall = 30 / 50
    assert abs(r["false_negative_rate"]["rate"] - (1 - recall)) < 1e-12
    share = r["false_alarm_share_of_warnings"]
    assert share["n"] == 40 and share["rate"] == 0.25 != r["false_positive_rate"]["rate"]   # 1 - precision


def test_single_class_samples_say_not_enough_data():
    quiet = ea.rates(pairs(tn=200, fp=3))
    assert quiet["false_negative_rate"]["rate"] is None and quiet["false_negative_rate"]["status"] == "not enough data"
    assert quiet["false_negative_rate"]["reason"] and quiet["false_negative_rate"]["ci95"] is None
    stormy = ea.rates(pairs(tp=40, fn=5))
    assert stormy["false_positive_rate"]["rate"] is None and stormy["false_positive_rate"]["status"] == "not enough data"
    assert ea.rates(pairs(tp=5, tn=5))["false_positive_rate"]["status"] == "not enough data"  # under 30


def test_zero_errors_is_not_zero_risk():
    r = ea.rates(pairs(tp=60, tn=500))
    fpr = r["false_positive_rate"]
    assert fpr["rate"] == 0 and fpr["ci95"][1] > 0
    assert "does not establish zero future risk" in ea.analyse([])["zero_errors_note"]


def rows(margins_observed):
    return [{"margin": m, "observed": o, "current_prediction": m is not None and m >= 0} for m, o in margins_observed]


SAMPLE = rows([(None, False)] * 50 + [(-100, False)] * 300 + [(-40, False)] * 20 + [(-40, True)] * 10 +
              [(-5, True)] * 5 + [(20, True)] * 30 + [(20, False)] * 2 + [(-100, True)] * 15)


def test_threshold_tradeoff_is_monotone():
    points = sorted(ea.sweep(SAMPLE), key=lambda p: p["offset_pct"])
    fa = [p["confusion"]["false_alarm"] for p in points]
    missed = [p["confusion"]["missed_disruption"] for p in points]
    # Easier thresholds (more negative offsets) never reduce false alarms and never add misses.
    assert fa == sorted(fa, reverse=True) and missed == sorted(missed)
    assert sum(p["current_thresholds"] for p in points) == 1
    assert all(p["n"] == len(SAMPLE) for p in points)
    assert "easier to trigger" in ea.tradeoff_sentence(points)


def test_missing_data_never_warns_or_counts_as_quiet():
    assert ea.day_margin([{"available": False, "metric": "x", "margin_pct": None}]) is None
    assert ea.day_margin([{"available": True, "metric": "alert_present", "triggered": True}]) > 0
    point = ea.sweep(rows([(None, True)]), offsets=(-75,))[0]
    assert point["confusion"]["missed_disruption"] == 1  # unknown is not a correct "quiet" call


def test_configurable_costs_and_sensitivity():
    points = ea.sweep(SAMPLE)
    s = ea.scenario_loss(points, c_fp=2, c_fn=7)
    p0 = next(p for p in points if p["offset_pct"] == 0)
    assert next(x for x in s["losses"] if x["offset_pct"] == 0)["loss"] == p0["confusion"]["false_alarm"] * 2 + p0["confusion"]["missed_disruption"] * 7
    assert s["assumed"] is True and "not measured" in s["label"]
    table = ea.sensitivity(points, ea.rates((r["current_prediction"], r["observed"]) for r in SAMPLE))["rows"]
    best = [row["best_offset_pct"] for row in table]
    assert best == sorted(best, reverse=True)  # costlier misses never push toward harder thresholds
    assert best[-1] < best[0]                    # and here they move to an easier setting
    assert [row["ratio"] for row in table] == list(ea.RATIOS)


def test_weather_labels_are_separate_from_operating_decisions():
    from app import historical
    day = {"id": "x", "day": "2024-01-09", "as_of": "2024-01-09T10:00:00+00:00", "decision_day": "2024-01-09",
           "reconstruction": "observation", "selection_gradable": True, "recommendation": "NORMAL", "hazard": "winter",
           "rule_margin_pct": -100.0, "outcome": {"gradable": True, "disruptive": True}}
    closed = {"day": "2024-01-09", "institution": "Ames schools", "institution_type": "school", "status": "CLOSED",
              "verification": "official", "cause": "weather"}
    plain = historical.metrics([{**day, "proxy_records": []}])["error_analysis"]["observation"]
    with_proxy = historical.metrics([{**day, "proxy_records": [closed]}])["error_analysis"]["observation"]
    assert plain["weather"] == with_proxy["weather"]               # closures never enter weather error counts
    assert plain["weather"]["confusion"]["missed_disruption"] == 1  # a missed weather disruption ...
    text = json.dumps(plain).lower()
    assert "unsafe" not in text and "decision_quality" not in text  # ... is not called an unsafe decision
    assert "not proof" in plain["label"].lower()


def snapshot(level=0, sources_ok=True, road_rank=0):
    hz = {"hazard": "winter", "label": "Winter weather", "level": level, "level_name": ["none", "minor", "significant", "extreme"][level],
          "score": 60 if level else 0, "window_start": "2026-01-12T12:00:00Z" if level else None, "window_end": "2026-01-12T16:00:00Z" if level else None}
    sources = [{"adapter": a, "status": "ok" if sources_ok else "unavailable"} for a in ("nws_grid", "nws_alerts", "iem_roads")]
    return {"facility": {"id": "IA-AMES-SC", "timezone": "America/Chicago", "hours": {"open": "07:30", "close": "16:30"}},
            "posture": {"decision_day": "2026-01-12"}, "hazards": {"winter": hz}, "sources": sources,
            "features": {"road_worst_rank": road_rank}, "roster": {"expected_in_building": 251, "essential_in_building": 38}}


def test_action_risk_is_qualitative_and_missing_inputs_are_unknown():
    timing, emp = load_thresholds().timing, load_employees()
    calm = assess_actions(snapshot(), emp, timing)
    assert {s["weather_exposure"] for s in calm["scenarios"]} == {"lower"}
    missing = assess_actions(snapshot(sources_ok=False), emp, timing)
    assert {s["weather_exposure"] for s in missing["scenarios"]} == {"unknown"}
    assert any("Not evidence of safe conditions" in m for m in missing["missing_inputs"])
    storm = assess_actions(snapshot(level=2), emp, timing)   # 06:00-10:00 local: the AM commute
    by = {s["action"]: s for s in storm["scenarios"]}
    assert by["NORMAL"]["weather_exposure"] == "elevated"
    assert by["CLOSED"]["people_travelling"] == 38 and by["CLOSED"]["weather_exposure"] == "moderate"
    assert [s["action"] for s in storm["scenarios"]] == ["NORMAL", "DELAYED_ARRIVAL", "TELEWORK", "CLOSED"]
    assert storm["quantitative"] is False and storm["experimental"] is True
    def keys(o):
        return [k for k, v in o.items() for k in [k, *keys(v)]] if isinstance(o, dict) else [k for v in o for k in keys(v)] if isinstance(o, list) else []
    assert not [k for k in keys(storm) if any(w in k for w in ("probab", "cost_usd", "loss", "injur"))]
    assert "$" not in json.dumps(storm)


def test_endpoint_is_read_only(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "db_path", tmp_path / "risk.db")
    from app.main import app
    from app.routers import risk
    old = db._engine
    engine = db.make_engine(f"sqlite:///{tmp_path / 'risk.db'}"); db.set_engine(engine)
    try:
        monkeypatch.setattr(risk.snapshots, "get", lambda sid: snapshot(level=2) if sid == "s" else None)
        r = TestClient(app).get("/api/risk-tradeoffs", params={"snapshot_id": "s"})
        assert r.status_code == 200 and r.json()["actions"]["scenarios"]
        assert TestClient(app).get("/api/risk-tradeoffs", params={"snapshot_id": "nope"}).status_code == 404
        with db.session() as s:
            assert not s.exec(select(Decision)).all() and not s.exec(select(DecisionContext)).all()
    finally:
        db.set_engine(old); engine.dispose()
