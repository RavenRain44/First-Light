"""Engine tests: thresholds/margins, posture timing, confidence, counterfactuals, immutability."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from adapters.base import NormalizedInput, Point, SourceStatus
from app.facility import load_facility
from engine import confidence as conf
from engine.counterfactual import what_would_change
from engine.evaluate import assess
from engine.features import extract
from engine.posture import candidate_days, combine, decide
from engine.scoring import evaluate_rules, load_thresholds, score_hazards

CT = ZoneInfo("America/Chicago")
FAC = load_facility()
TH = load_thresholds()
NOW = datetime(2026, 10, 10, 18, tzinfo=timezone.utc)


def local(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=CT).astimezone(timezone.utc)


def series_input(id_, metric, unit, pts, role="forecast"):
    return NormalizedInput(id=id_, kind="series", role=role, metric=metric, unit=unit,
                           series=[Point(t=t, v=v) for t, v in pts], source="test", source_url="test://",
                           fetched_at=NOW, source_time=NOW)


def alert_input(event, onset, ends, certainty="Likely", severity="Severe"):
    data = {"id": f"test-{event}", "event": event, "severity": severity, "certainty": certainty, "urgency": "Expected",
            "onset": onset.isoformat(), "ends": ends.isoformat()}
    return NormalizedInput(id=f"alert:test-{event}", kind="alert", role="alert", metric="nws_alert", value=event,
                           data=data, source="test", source_url="test://", fetched_at=NOW)


def run(inputs, as_of):
    ctx = extract(inputs, as_of, horizon_end=as_of + timedelta(hours=48))
    rr = evaluate_rules(ctx, TH)
    hz = score_hazards(rr)
    return ctx, rr, hz, decide(hz, rr, as_of, FAC, TH)


# --- threshold evaluation and margins -----------------------------------------

def test_threshold_margin_absolute_and_percent():
    as_of = local(2026, 1, 13, 3)  # Tue 03:00 CST
    hours = [as_of + timedelta(hours=i) for i in range(24)]
    gust = [(t, 65.0 if i == 10 else 20.0) for i, t in enumerate(hours)]
    ctx, rr, hz, _ = run([series_input("fcst.wind_gust_mph", "wind_gust_mph", "mph", gust)], as_of)
    r = next(x for x in rr if x.rule_id == "wind.fcst_gust_warning")
    assert r.triggered and r.observed_value == 65.0 and r.threshold == 58
    assert r.margin_abs == pytest.approx(7.0)
    assert r.margin_pct == pytest.approx(12.1, abs=0.05)
    assert r.time_of_peak == hours[10]
    assert r.window_start == hours[10] and r.window_end == hours[10] + timedelta(hours=1)
    assert r.input_ids == ["fcst.wind_gust_mph"]
    adv = next(x for x in rr if x.rule_id == "wind.fcst_gust_advisory")
    assert adv.triggered and adv.margin_abs == pytest.approx(20.0)


def test_below_threshold_reports_negative_margin_and_untriggered():
    as_of = local(2026, 1, 13, 3)
    ice = [(as_of + timedelta(hours=i), 0.01) for i in range(5)]  # 0.05 in total
    _, rr, _, _ = run([series_input("fcst.ice_in", "ice_in", "in", ice)], as_of)
    r = next(x for x in rr if x.rule_id == "winter.fcst_ice_tenth_inch")
    assert not r.triggered and r.margin_abs == pytest.approx(-0.05)
    assert next(x for x in rr if x.rule_id == "winter.fcst_ice_any").triggered


def test_less_than_operator_for_cold():
    as_of = local(2026, 1, 13, 3)
    app = [(as_of + timedelta(hours=i), -38.0) for i in range(6)]
    _, rr, _, _ = run([series_input("fcst.apparent_temp_f", "apparent_temp_f", "degF", app)], as_of)
    r = next(x for x in rr if x.rule_id == "cold.fcst_wind_chill_extreme")
    assert r.triggered and r.margin_abs == pytest.approx(3.0)


def test_missing_signal_is_unavailable_not_triggered():
    _, rr, hz, p = run([], local(2026, 1, 13, 3))
    assert all(not r.triggered for r in rr)
    assert any(not r.available for r in rr)
    assert p.posture == "NORMAL"


def test_every_threshold_has_anchor_source_and_verified_flag():
    for r in TH.rules:
        assert r.anchor and r.source_url.startswith("https://") and isinstance(r.verified, bool)
        assert r.posture_effect in ("minor", "significant", "extreme")


# --- posture timing -------------------------------------------------------------

def ice_case(start_h, end_h, as_of):
    return [alert_input("Winter Storm Warning", local(2026, 1, 13, start_h), local(2026, 1, 13, end_h))], as_of


def test_ice_peaking_in_am_commute_is_delay_or_telework():
    # Warning-level winter hazard 03:00-05:00 + 3 h road recovery -> through 08:00: AM commute only
    inputs, as_of = ice_case(3, 5, local(2026, 1, 12, 20))
    assert run(inputs, as_of)[3].posture == "DELAYED_ARRIVAL"
    # 05:00-09:00 (+3 h -> 12:00) runs through the late morning -> telework
    inputs, as_of = ice_case(5, 9, local(2026, 1, 12, 20))
    assert run(inputs, as_of)[3].posture == "TELEWORK"


def test_severe_wind_arriving_midafternoon_is_early_dismissal():
    as_of = local(2026, 1, 13, 9)  # Tue 09:00
    inputs = [alert_input("High Wind Warning", local(2026, 1, 13, 14), local(2026, 1, 13, 20))]
    p = run(inputs, as_of)[3]
    assert p.posture == "EARLY_DISMISSAL"
    assert p.decision_day.isoformat() == "2026-01-13"


def test_same_hazard_overnight_only_stays_normal():
    as_of = local(2026, 1, 12, 20)
    inputs = [alert_input("High Wind Warning", local(2026, 1, 12, 22), local(2026, 1, 13, 4))]
    assert run(inputs, as_of)[3].posture == "NORMAL"


def test_extreme_in_morning_closes_and_tornado_now_shelters():
    as_of = local(2026, 1, 12, 20)
    inputs = [alert_input("Ice Storm Warning", local(2026, 1, 13, 2), local(2026, 1, 13, 12))]
    assert run(inputs, as_of)[3].posture == "CLOSED"
    as_of = local(2026, 1, 13, 13)
    inputs = [alert_input("Tornado Warning", local(2026, 1, 13, 12, 50), local(2026, 1, 13, 13, 30), certainty="Observed")]
    p = run(inputs, as_of)[3]
    assert p.posture == "CLOSED" and any("shelter" in g.lower() for g in p.guidance)


def test_afternoon_hands_decision_to_next_workday_and_weekend_skips():
    fri_eve = local(2026, 1, 16, 18)
    assert candidate_days(fri_eve, FAC)[-1].weekday() == 0  # Monday
    tue_4pm = local(2026, 1, 13, 16)
    inputs = [alert_input("Winter Storm Warning", local(2026, 1, 14, 4), local(2026, 1, 14, 7))]
    p = run(inputs, tue_4pm)[3]
    assert p.decision_day.isoformat() == "2026-01-14" and p.posture == "DELAYED_ARRIVAL"


def test_combine_delay_and_early_dismissal_becomes_telework():
    assert combine(["DELAYED_ARRIVAL", "EARLY_DISMISSAL"]) == "TELEWORK"
    assert combine(["NORMAL", "CLOSED", "DELAYED_ARRIVAL"]) == "CLOSED"
    assert combine([]) == "NORMAL"


# --- confidence -------------------------------------------------------------------

def statuses(names, status="ok"):
    return [SourceStatus(adapter=n, label=n, status=status) for n in names]


def test_confidence_drops_when_sources_missing():
    as_of = local(2026, 1, 13, 3)
    inputs = [series_input("fcst.wind_gust_mph", "wind_gust_mph", "mph", [(as_of, 20.0)]),
              series_input("obs.wind_gust_mph", "wind_gust_mph", "mph", [(as_of, 21.0)], role="observation")]
    ctx, rr, hz, _ = run(inputs, as_of)
    full = conf.compute(statuses(conf.EXPECTED["live"]), inputs, ctx, rr, hz, "live")
    partial = conf.compute(statuses(["nws_alerts", "nws_grid"]) + statuses(["iem_obs", "iem_roads"], "not_applicable"),
                           inputs, ctx, rr, hz, "live")
    assert full.level == "high"
    assert partial.score < full.score
    assert next(f for f in partial.factors if f.name == "completeness").score < 1


def test_confidence_flags_forecast_alert_disagreement():
    as_of = local(2026, 8, 10, 10)
    inputs = [alert_input("Severe Thunderstorm Warning", as_of, as_of + timedelta(hours=1)),
              series_input("fcst.wind_gust_mph", "wind_gust_mph", "mph", [(as_of + timedelta(hours=i), 15.0) for i in range(24)])]
    ctx, rr, hz, _ = run(inputs, as_of)
    c = conf.compute(statuses(conf.EXPECTED["live"]), inputs, ctx, rr, hz, "live")
    agree = next(f for f in c.factors if f.name == "agreement")
    assert agree.score < 1 and "weaker" in agree.explanation


# --- what would change ------------------------------------------------------------

def test_counterfactual_reports_posture_change():
    as_of = local(2026, 1, 12, 20)
    hours = [local(2026, 1, 13, 5) + timedelta(hours=i) for i in range(4)]
    ice = [(t, 0.08) for t in hours]  # 0.32 in during the AM commute -> extreme
    inputs = [series_input("fcst.ice_in", "ice_in", "in", ice)]
    ctx, rr, hz, p = run(inputs, as_of)
    assert p.posture == "CLOSED"
    changes = what_would_change(ctx, TH, FAC, p.posture, rr)
    c = next(c for c in changes if c.rule_id == "winter.fcst_ice_quarter_inch")
    assert c.new_posture in ("TELEWORK", "DELAYED_ARRIVAL")
    assert "0.25 in" in c.text and "0.32 in" in c.text


# --- snapshot immutability -------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path):
    from app import db
    old = db._engine
    db.set_engine(db.make_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}"))
    yield db
    db.set_engine(old)


def _store_minimal(as_of):
    from app import snapshots
    a = assess([], statuses(conf.EXPECTED["live"]), FAC, as_of, "live")
    snap = snapshots.build_snapshot_dict(FAC, a, [], [], "live")
    snap.update(ai={"headline": "x"}, model_id="test", prompt_version="t")
    return snapshots.store(snap)


def test_snapshot_cannot_be_updated_or_deleted(temp_db):
    from sqlalchemy.exc import DBAPIError

    from app import snapshots
    snap = _store_minimal(local(2026, 1, 13, 3))
    loaded = snapshots.get(snap["snapshot_id"])
    assert loaded["integrity_ok"] is True
    with temp_db.get_engine().begin() as c, pytest.raises(DBAPIError, match="immutable"):
        c.execute(text("UPDATE snapshot SET posture='CLOSED' WHERE snapshot_id=:i"), {"i": snap["snapshot_id"]})
    with temp_db.get_engine().begin() as c, pytest.raises(DBAPIError, match="immutable"):
        c.execute(text("DELETE FROM snapshot WHERE snapshot_id=:i"), {"i": snap["snapshot_id"]})


def test_decisions_are_append_only(temp_db):
    from sqlalchemy.exc import DBAPIError

    from app.models import Decision
    snap = _store_minimal(local(2026, 1, 13, 3))
    with temp_db.session() as s:
        s.add(Decision(snapshot_id=snap["snapshot_id"], facility_id=FAC.id, decided_by="tester",
                       decision_posture="NORMAL", recommended_posture="NORMAL", agreed_with_recommendation=True,
                       decided_at=NOW))
        s.commit()
    with temp_db.get_engine().begin() as c, pytest.raises(DBAPIError, match="append-only"):
        c.execute(text("UPDATE decision SET decision_posture='CLOSED'"))
