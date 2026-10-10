"""Readiness (adapted Cooper Color Code): WHITE / YELLOW / ORANGE / RED."""
from datetime import datetime, timedelta, timezone

from adapters.base import SourceStatus
from engine import confidence as conf
from engine.readiness import assess_readiness
from tests.test_engine import FAC, TH, alert_input, local, run, series_input


def ready(inputs, as_of):
    ctx, rr, hz, p = run(inputs, as_of)
    c = conf.compute([SourceStatus(adapter=n, label=n, status="ok") for n in conf.EXPECTED["live"]], inputs, ctx, rr, hz, "live")
    return assess_readiness(hz, rr, p, c, ctx.alerts, as_of, FAC, TH), p


def test_quiet_is_white_with_slow_recheck():
    as_of = local(2026, 1, 13, 9)
    gust = [(as_of + timedelta(hours=i), 12.0) for i in range(24)]
    r, _ = ready([series_input("fcst.wind_gust_mph", "wind_gust_mph", "mph", gust),
                  series_input("obs.wind_gust_mph", "wind_gust_mph", "mph", [(as_of, 12.0)], role="observation")], as_of)
    assert r.level == "WHITE" and r.recheck_minutes == 360 and r.decide_by is None


def test_watch_or_near_miss_is_yellow():
    as_of = local(2026, 1, 13, 9)
    r, p = ready([alert_input("Winter Storm Watch", local(2026, 1, 15, 0), local(2026, 1, 16, 0), certainty="Possible")], as_of)
    assert p.posture == "NORMAL" and r.level == "YELLOW"
    gust = [(as_of + timedelta(hours=i), 40.0) for i in range(24)]  # 40 of 58 mph: near miss
    r, _ = ready([series_input("fcst.wind_gust_mph", "wind_gust_mph", "mph", gust)], as_of)
    assert r.level == "YELLOW" and any("approaching" in x for x in r.reasons)


def test_warning_for_tomorrow_evening_is_orange_with_deadline():
    as_of = local(2026, 1, 12, 9)  # Mon 09:00; ice arrives Tue 05:00
    r, p = ready([alert_input("Winter Storm Warning", local(2026, 1, 13, 5), local(2026, 1, 13, 9))], as_of)
    # Monday morning: today is quiet, so the posture is for today (NORMAL), but the warning makes it ORANGE
    assert r.level == "ORANGE"


def test_announcement_deadline_close_is_red():
    as_of = local(2026, 1, 13, 3)  # 03:00, announce-by 04:30
    r, p = ready([alert_input("Winter Storm Warning", local(2026, 1, 13, 5), local(2026, 1, 13, 9))], as_of)
    assert p.posture in ("DELAYED_ARRIVAL", "TELEWORK")
    assert r.level == "RED" and r.decide_by == local(2026, 1, 13, 4, 30) and r.recheck_minutes == 10


def test_early_dismissal_deadline_is_release_lead_before_arrival():
    as_of = local(2026, 1, 13, 8)
    r, p = ready([alert_input("High Wind Warning", local(2026, 1, 13, 14), local(2026, 1, 13, 20))], as_of)
    assert p.posture == "EARLY_DISMISSAL"
    assert r.decide_by == local(2026, 1, 13, 12) and r.level == "ORANGE"
    r2, _ = ready([alert_input("High Wind Warning", local(2026, 1, 13, 14), local(2026, 1, 13, 20))], local(2026, 1, 13, 11))
    assert r2.level == "RED"


def test_hazard_in_progress_is_red():
    as_of = local(2026, 1, 13, 13)
    r, _ = ready([alert_input("Tornado Warning", local(2026, 1, 13, 12, 50), local(2026, 1, 13, 13, 30), certainty="Observed")], as_of)
    assert r.level == "RED" and any("now" in x for x in r.reasons)


def test_readiness_never_changes_posture():
    as_of = local(2026, 1, 13, 3)
    inputs = [alert_input("Winter Storm Warning", local(2026, 1, 13, 5), local(2026, 1, 13, 9))]
    assert run(inputs, as_of)[3].posture == ready(inputs, as_of)[1].posture
