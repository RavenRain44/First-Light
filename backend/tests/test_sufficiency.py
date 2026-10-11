"""Evidence sufficiency: missing data must never read as a supported all-clear.

Deterministic synthetic inputs, a frozen evaluation time and isolated temporary databases. No paid AI
calls, no notifications.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from adapters.base import NormalizedInput, Point, SourceStatus
from ai import agent, fallback
from app import db, snapshots
from app.config import settings
from app.facility import load_facility
from app.models import DecisionContext, Snapshot
from engine import sufficiency
from engine.evaluate import assess

CT = ZoneInfo("America/Chicago")
FAC = load_facility()
AS_OF = datetime(2026, 1, 13, 3, tzinfo=CT).astimezone(timezone.utc)  # Tue 03:00 CST; window runs to 18:00
LIVE = ["nws_alerts", "nws_grid", "iem_obs", "iem_roads", "iem_rwis", "iem_outlook"]


def status(adapter, s="ok", detail=None):
    return SourceStatus(adapter=adapter, label=adapter.replace("_", " "), status=s, detail=detail)


def forecast(metric="temp_f", value=30.0, hours=48, issued_h=2.0, fetched_h=0.1, start=AS_OF, step=1):
    pts = [Point(t=start + timedelta(hours=i), v=value) for i in range(0, hours, step)]
    return NormalizedInput(id=f"fcst.{metric}", kind="series", role="forecast", metric=metric, unit="x", series=pts,
                           source="test", source_url="test://", fetched_at=AS_OF - timedelta(hours=fetched_h),
                           source_time=AS_OF - timedelta(hours=issued_h))


def benign_forecast(**kw):
    return [forecast("temp_f", 30.0, **kw), forecast("apparent_temp_f", 25.0, **kw), forecast("wind_gust_mph", 15.0, **kw),
            forecast("wind_speed_mph", 8.0, **kw), forecast("ice_in", 0.0, **kw), forecast("snow_in", 0.0, **kw),
            forecast("qpf_in", 0.0, **kw)]


def observation(age_h=0.5, fetched_h=0.1):
    t = AS_OF - timedelta(hours=age_h)
    return NormalizedInput(id="obs.temp_f", kind="series", role="observation", metric="temp_f", unit="degF",
                           series=[Point(t=t - timedelta(hours=i), v=28.0) for i in range(6)], source="test",
                           source_url="test://", fetched_at=AS_OF - timedelta(hours=fetched_h), source_time=t)


def no_alerts(fetched_h=0.1):
    return NormalizedInput(id="alert:none", kind="scalar", role="alert", metric="nws_alert", value="none in effect",
                           source="test", source_url="test://", fetched_at=AS_OF - timedelta(hours=fetched_h))


def ice_storm_warning():
    onset, ends = AS_OF + timedelta(hours=2), AS_OF + timedelta(hours=14)
    data = {"id": "test-ice", "event": "Ice Storm Warning", "severity": "Severe", "certainty": "Likely", "urgency": "Expected",
            "onset": onset.isoformat(), "ends": ends.isoformat()}
    return NormalizedInput(id="alert:test-ice", kind="alert", role="alert", metric="nws_alert", value="Ice Storm Warning",
                           data=data, source="test", source_url="test://", fetched_at=AS_OF - timedelta(minutes=5),
                           source_time=AS_OF - timedelta(hours=1))


def run(inputs, statuses, mode="live", as_of=AS_OF):
    return assess(inputs, statuses, FAC, as_of, mode)


def full_benign():
    return benign_forecast() + [observation(), no_alerts()], [status(a) for a in LIVE]


# --- the policy ------------------------------------------------------------------------------------

def test_empty_inputs_and_statuses_are_explicitly_insufficient():
    a = run([], [])
    s = a.sufficiency
    assert s.status == "insufficient" and not s.supports_all_clear and s.reason_required
    assert a.posture.posture == "NORMAL"  # only the fallback; missing data never picks a posture
    assert any("forecast" in r.lower() for r in s.reasons)
    assert "Insufficient current data" in a.readiness.reasons[0] and a.readiness.level == "YELLOW"
    assert any("not an all-clear" in w for w in a.watch_next_6h)


def test_all_sources_unavailable_give_useful_reasons():
    st = [status(x, "unavailable", "ConnectTimeout: timed out") for x in LIVE]
    s = run([], st).sufficiency
    assert s.status == "insufficient"
    assert {"nws grid", "nws alerts", "iem obs"} <= set(s.missing_sources)
    assert any("ConnectTimeout" in r for r in s.reasons) and any("not the same as none" in r for r in s.reasons)


def test_checked_empty_alert_feed_alone_is_not_an_all_clear():
    s = run([no_alerts()], [status("nws_alerts"), status("nws_grid", "unavailable"), status("iem_obs", "unavailable")]).sufficiency
    alerts = next(c for c in s.checks if c.name == "alerts")
    assert alerts.status == "checked_none"  # checked and empty, not "unavailable"
    assert s.status == "insufficient" and not s.supports_all_clear
    assert any("does not show conditions are safe" in r for r in s.reasons)


def test_unavailable_alert_feed_differs_from_checked_empty_feed():
    inputs, st = full_benign()
    ok = run(inputs, st).sufficiency
    down = run([i for i in inputs if i.role != "alert"],
               [status("nws_alerts", "unavailable", "HTTP 503") if x.adapter == "nws_alerts" else x for x in st]).sufficiency
    assert next(c for c in ok.checks if c.name == "alerts").status == "checked_none" and ok.status == "sufficient"
    assert next(c for c in down.checks if c.name == "alerts").status == "missing" and down.status == "limited"


@pytest.mark.parametrize("kw", [{"issued_h": 20}, {"issued_h": 1, "fetched_h": 5}])
def test_stale_only_live_evidence_is_insufficient(kw):
    """An old forecast, or a fresh-looking one that was retrieved hours ago (stale cache served after a retry)."""
    inputs = benign_forecast(**kw) + [observation(age_h=6, fetched_h=6), no_alerts(fetched_h=6)]
    s = run(inputs, [status(a) for a in LIVE]).sufficiency
    assert s.status == "insufficient" and not s.supports_all_clear
    assert s.stale_sources and next(c for c in s.checks if c.name == "forecast").status == "stale"


def test_forecast_that_does_not_cover_the_decision_window_is_partial():
    s = run(benign_forecast(hours=6) + [observation(), no_alerts()], [status(a) for a in LIVE]).sufficiency
    fc = next(c for c in s.checks if c.name == "forecast")
    assert fc.status == "partial" and s.forecast_coverage < sufficiency.COVERAGE_MIN and s.status == "insufficient"


def test_fresh_covered_benign_weather_supports_normal():
    a = run(*full_benign())
    assert a.posture.posture == "NORMAL" and a.sufficiency.status == "sufficient"
    assert a.sufficiency.supports_all_clear and not a.sufficiency.reason_required and not a.sufficiency.reasons
    assert a.readiness.level == "WHITE"


def test_three_hourly_archive_forecast_counts_as_coverage():
    inputs = benign_forecast(step=3) + [observation(), no_alerts()]
    st = [status(a) for a in ("iem_vtec", "iem_mos", "iem_obs", "iem_roads", "iem_rwis", "iem_outlook")]
    assert run(inputs, st, mode="replay").sufficiency.forecast_coverage == 1.0


def test_missing_optional_or_inapplicable_sources_do_not_block():
    inputs, _ = full_benign()
    st = [status("nws_alerts"), status("nws_grid"), status("iem_obs"), status("iem_roads", "empty"),
          status("iem_rwis", "unavailable", "timeout"), status("iem_outlook", "not_applicable", "source covers IA only")]
    s = run(inputs, st).sufficiency
    assert s.status == "sufficient" and s.supports_all_clear
    assert {c.name: c.status for c in s.checks}["iem_rwis"] == "optional_missing"
    assert {c.name: c.status for c in s.checks}["iem_outlook"] == "not_applicable"


def test_credible_severe_hazard_survives_other_source_failures():
    st = [status("nws_alerts")] + [status(x, "unavailable", "timeout") for x in LIVE[1:]]
    a = run([ice_storm_warning()], st)
    assert a.posture.posture != "NORMAL"  # the known hazard is not downgraded
    assert a.sufficiency.status == "limited" and a.sufficiency.hazard_evidence
    assert any("never a milder one" in r for r in a.sufficiency.reasons)
    assert a.readiness.level in ("ORANGE", "RED")


def test_replay_is_judged_at_its_own_as_of_and_labelled():
    """Archive data downloaded years later is not stale for the replayed moment."""
    old = datetime(2023, 2, 22, 4, tzinfo=CT).astimezone(timezone.utc)
    def at(i, delta):
        return i.model_copy(update={"fetched_at": datetime(2026, 10, 10, tzinfo=timezone.utc),
                                    "source_time": i.source_time - (AS_OF - old) if i.source_time else None,
                                    "series": [Point(t=p.t - (AS_OF - old), v=p.v) for p in i.series or []] or None})
    inputs = [at(i, None) for i in benign_forecast(step=3) + [observation()]]
    st = [status(a) for a in ("iem_vtec", "iem_mos", "iem_obs")]
    s = run(inputs, st, mode="replay", as_of=old).sufficiency
    assert s.status != "insufficient" and s.supports_all_clear and "Replay" in s.mode_note
    assert s.evaluated_as_of == old
    # The same old evidence evaluated as live weather "now" is stale.
    live_now = run(inputs, [status(a) for a in LIVE], mode="live", as_of=AS_OF).sufficiency
    assert live_now.status == "insufficient"


def test_demo_mode_is_labelled(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    assert "Demo" in run(*full_benign()).sufficiency.mode_note


# --- briefs ---------------------------------------------------------------------------------------

def snapshot_dict(a, inputs=(), statuses=(), mode="live"):
    snap = snapshots.build_snapshot_dict(FAC, a, list(inputs), list(statuses), mode)
    snap.update(model_id="deterministic-fallback", prompt_version="test", ai={})
    return snap


def test_deterministic_brief_says_insufficient_and_never_all_clear():
    snap = snapshot_dict(run([], []))
    b = fallback.build(snap)
    assert b.headline.startswith("Insufficient current data") and "Normal" in b.headline
    assert "not evidence of safe conditions" in b.summary and "Insufficient" in b.rationale_paragraph
    assert "No NWS alert, forecast, observation or road threshold is crossed" not in b.rationale_paragraph
    assert agent.sufficiency_problems(b, snap) == []
    assert agent.validate(b, snap, agent.allowed_numbers(snap)) == []


def test_ai_brief_claiming_safety_on_missing_data_is_rejected():
    snap = snapshot_dict(run([], []))
    good = fallback.build(snap)
    claims = good.model_copy(update={"headline": "Normal operations: conditions are clear",
                                     "summary": "Normal is recommended. Roads look safe and there are no hazards."})
    problems = agent.sufficiency_problems(claims, snap)
    assert any("must say current data is insufficient" in p for p in problems)
    assert any("must not describe conditions as safe" in p for p in problems)


def test_supported_normal_brief_is_unchanged():
    inputs, st = full_benign()
    snap = snapshot_dict(run(inputs, st), inputs, st)
    b = fallback.build(snap)
    assert "Insufficient" not in b.headline and "No NWS alert, forecast, observation or road threshold is crossed" in b.rationale_paragraph
    assert agent.sufficiency_problems(b.model_copy(update={"summary": "Normal is recommended. No hazards are expected."}), snap) == []


def test_ai_context_carries_the_computed_state():
    from ai.tools import snapshot_summary
    view = snapshot_summary(snapshot_dict(run([], [])))["evidence_sufficiency"]
    assert view["status"] == "insufficient" and view["supports_all_clear"] is False


# --- persistence, compatibility and the decision API ---------------------------------------------

@pytest.fixture
def tmpdb(tmp_path, monkeypatch):
    old = db._engine
    engine = db.make_engine(f"sqlite:///{tmp_path / 'suff.db'}")
    db.set_engine(engine)
    import app.camera_archive as ca
    async def no_capture(*a, **k): return None
    monkeypatch.setattr(ca, "capture", no_capture)
    monkeypatch.setattr(settings, "demo_mode", False)
    yield
    db.set_engine(old)
    engine.dispose()


def stored(a, inputs=(), statuses=()):
    return snapshots.store(snapshot_dict(a, inputs, statuses))


def test_state_persists_and_round_trips(tmpdb):
    snap = stored(run([], []))
    back = snapshots.get(snap["snapshot_id"])
    assert back["sufficiency"]["status"] == "insufficient" and back["integrity_ok"]
    with db.session() as s:
        assert s.get(Snapshot, snap["snapshot_id"]).sufficiency_status == "insufficient"


def test_older_snapshot_without_the_field_keeps_its_hash_and_is_not_sufficient(tmpdb):
    snap = snapshot_dict(run(*full_benign()))
    del snap["sufficiency"]  # as written before sufficiency existed
    snap["content_sha256"] = snapshots.content_hash(snap)
    values = {k: snapshots._dumps(snap[k.removesuffix("_json")]) for k in
              ("facility_json", "roster_json", "inputs_json", "sources_json", "signals_json", "rules_json", "hazards_json",
               "posture_json", "confidence_json", "changes_json", "readiness_json", "analogs_json", "features_json", "ai_json")}
    with db.session() as s:
        s.add(Snapshot(**values, snapshot_id=snap["snapshot_id"], facility_id=FAC.id, as_of=datetime.fromisoformat(snap["as_of"]),
                       created_at=datetime.fromisoformat(snap["created_at"]), mode="live", posture="NORMAL", opm_label="Open",
                       confidence="high", confidence_score=1, readiness_level="WHITE", thresholds_version=snap["thresholds_version"],
                       thresholds_sha256=snap["thresholds_sha256"], model_id=snap["model_id"], prompt_version=snap["prompt_version"],
                       watch_json=snapshots._dumps(snap["watch_next_6h"]), content_sha256=snap["content_sha256"]))
        s.commit()
    back = snapshots.get(snap["snapshot_id"])
    assert back["sufficiency"] is None and back["integrity_ok"]  # history not rewritten
    legacy = sufficiency.for_snapshot(back)
    assert legacy["status"] == "not_recorded" and legacy["reason_required"] and not legacy["supports_all_clear"]
    client = TestClient(__import__("app.main", fromlist=["app"]).app)
    r = client.post("/api/decisions", json={"snapshot_id": snap["snapshot_id"], "decided_by": "Pat Lee", "decision_posture": "NORMAL"})
    assert r.status_code == 422


@pytest.mark.parametrize("posture", ["NORMAL", "CLOSED"])
@pytest.mark.parametrize("reason", [None, "", "   \n\t "])
def test_decision_under_insufficient_evidence_needs_a_real_reason(tmpdb, posture, reason):
    from app.main import app
    snap = stored(run([], []))
    body = {"snapshot_id": snap["snapshot_id"], "decided_by": "Pat Lee", "decision_posture": posture}
    if reason is not None:
        body["override_reason"] = reason
    r = TestClient(app).post("/api/decisions", json=body)
    assert r.status_code == 422 and "insufficient" in r.text


def test_manual_decision_keeps_reason_and_evidence_status(tmpdb):
    from app.main import app
    client = TestClient(app)
    snap = stored(run([], []))
    r = client.post("/api/decisions", json={"snapshot_id": snap["snapshot_id"], "decided_by": "Pat Lee",
                                            "decision_posture": "NORMAL", "override_reason": "  Called the county EOC: roads are clear.  "})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["agreed_with_recommendation"] is False  # manual, not ordinary agreement with a supported suggestion
    assert d["override_reason"] == "Called the county EOC: roads are clear."
    assert d["evidence_status"] == "insufficient" and d["decision_basis"] == "manual_insufficient_evidence"
    listed = next(x for x in client.get("/api/decisions").json() if x["id"] == d["id"])
    assert listed["evidence_status"] == "insufficient" and listed["decision_basis"] == "manual_insufficient_evidence"
    with db.session() as s:
        assert s.get(DecisionContext, d["id"]).evidence_status == "insufficient"


def test_provisional_backup_requires_manager_verification_reason(tmpdb):
    from app.main import app
    client = TestClient(app)
    records = [i.model_copy(update={"source_time": None, "data": {"weather_fallback": True, "live_retrieval_only": True}})
               for i in benign_forecast() if i.metric != "ice_in"]
    st = [status(a) for a in LIVE]
    snap = stored(run(records, st), records, st)
    body = {"snapshot_id": snap["snapshot_id"], "decided_by": "Pat Lee", "decision_posture": "NORMAL"}
    rejected = client.post("/api/decisions", json=body)
    assert rejected.status_code == 422 and "provisional" in rejected.text
    accepted = client.post("/api/decisions", json={**body, "override_reason": "Verified local warnings and road conditions with county staff."})
    assert accepted.status_code == 201, accepted.text
    decision = accepted.json()
    assert decision["decision_basis"] == "manual_provisional_forecast" and decision["evidence_status"] == "limited"
    assert decision["agreed_with_recommendation"] is False


def test_supported_decision_is_ordinary_agreement(tmpdb):
    from app.main import app
    inputs, st = full_benign()
    snap = stored(run(inputs, st), inputs, st)
    r = TestClient(app).post("/api/decisions", json={"snapshot_id": snap["snapshot_id"], "decided_by": "Pat Lee", "decision_posture": "NORMAL"})
    assert r.status_code == 201
    assert r.json()["agreed_with_recommendation"] is True and r.json()["decision_basis"] == "recommendation"
    assert r.json()["evidence_status"] == "sufficient"
