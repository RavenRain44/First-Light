"""Operational grading, independent labels, cached AI and safe full-engine proposals."""
import asyncio
import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app import db, feedback, past_decisions, policy, snapshots, storage
from app.config import settings
from app.facility import load_facility
from app.main import app
from app.models import (Decision, DecisionContext, DecisionIntent, DecisionReview, FeedbackAnalysis,
                        HistoricalArtifact, HistoricalEvaluation, Snapshot)
from engine.scoring import load_base_thresholds, load_thresholds

FAC = load_facility()
AT = datetime(2024, 1, 2, 10, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    old = db._engine
    monkeypatch.setattr(settings, "db_path", tmp_path / "feedback.db")
    engine = db.make_engine(f"sqlite:///{settings.db_path}")
    db.set_engine(engine)
    monkeypatch.setattr(settings, "model_provider", "none")
    monkeypatch.setattr(settings, "threshold_admin_token", "manager-secret")
    saved = {}
    monkeypatch.setattr(snapshots, "get", saved.get)
    def add(posture="NORMAL", recommendation="NORMAL", day="2024-01-02", demo=False, mode="live", at=None):
        when = at or AT
        sid = str(len(saved))
        snap = {"snapshot_id":sid,"mode":mode,"facility":FAC.model_dump(mode="json"),"as_of":when.isoformat(),
                "posture":{"posture":recommendation,"decision_day":day,"reasons":["Recorded reason"]},
                "hazards":{},"alerts":[],"features":{},"thresholds_version":"base","thresholds_sha256":"sha","event_id":None}
        saved[sid] = snap
        values = {f:"{}" for f in Snapshot.model_fields if f.endswith("_json")}
        values.update(posture_json=json.dumps(snap["posture"]))
        with db.session() as s:
            s.add(Snapshot(**values,snapshot_id=sid,facility_id=FAC.id,as_of=when,created_at=when,mode=mode,posture=recommendation,
                           opm_label="Test",confidence="medium",confidence_score=.5,thresholds_version="base",thresholds_sha256="sha",
                           model_id="none",prompt_version="test",content_sha256="test"));s.flush()
            d=Decision(snapshot_id=sid,facility_id=FAC.id,decided_by="Pat Manager",decision_posture=posture,
                       recommended_posture=recommendation,agreed_with_recommendation=posture==recommendation,decided_at=when)
            s.add(d);s.flush();s.add(DecisionContext(decision_id=d.id,demo_mode=demo,evidence_status="sufficient"));s.commit();s.refresh(d)
        return d, snap
    yield add
    db.set_engine(old);engine.dispose()


def outcome(actual=False, complete=True):
    return {"summary":"Independent observed weather", "severe_impact":actual,"amw_peak_gust_mph":60 if actual else 10,
            "coverage":{"complete":complete,"expected_hours":24,"observed_hours":24 if complete else 1}}


def assess(d,snap,actual=False,complete=True):
    return feedback.record_assessment(d,snap,outcome(actual,complete),AT+timedelta(days=2))


def test_intentions_reviews_corrections_and_readonly_decision(env):
    d,snap=env("CLOSED")
    c=TestClient(app)
    url=f"/api/decisions/{d.id}"
    initial=c.post(url+"/intention",json={"actor":"Manager","objective":"Keep staff safe"})
    assert initial.status_code==201 and initial.json()["retrospective"]
    assert c.post(url+"/intention",json={"actor":"Manager","objective":"Changed objective"}).status_code==409
    assert c.post(url+"/intention",json={"actor":"Manager","objective":"Changed objective","expected_id":initial.json()["id"]}).status_code==422
    assert c.post(url+"/intention",json={"actor":"Manager","objective":"Changed objective","expected_id":initial.json()["id"],"correction_reason":"Added continuity goal"}).status_code==201
    body={"actor":"Manager","verdict":"mixed","achievement":"partly_achieved","note":"Tasks continued remotely","evidence_refs":["https://example.test/report"]}
    r=c.post(url+"/grade",json=body);assert r.status_code==201
    assert c.post(url+"/grade",json=body).status_code==409
    assert c.post(url+"/grade",json={**body,"expected_id":r.json()["id"]}).status_code==422
    assert c.post(url+"/grade",json={**body,"verdict":"good_call","expected_id":r.json()["id"],"correction_reason":"Verified remote task completion"}).status_code==201
    value=c.get(url+"/grade").json()
    assert len(value["intentions"])==2 and len(value["reviews"])==2
    assert value["decision"]["decision_posture"]=="CLOSED" and value["decision"]["recommended_posture"]=="NORMAL"
    assert feedback.statistics()["eligible_count"]==0  # Opinions never supply labels.
    with db.session() as s, pytest.raises(IntegrityError):
        row=s.get(DecisionIntent,initial.json()["id"]);row.objective="rewrite";s.add(row);s.commit()


@pytest.mark.parametrize("url",["file:///etc/passwd","https://user:secret@example.test/report","javascript:alert(1)"])
def test_evidence_urls_reject_credentials_and_unsafe_protocols(env,url):
    d,_=env()
    assert TestClient(app).post(f"/api/decisions/{d.id}/grade",json={"actor":"Manager","verdict":"good_call","evidence_refs":[url]}).status_code==422


def test_independent_stats_first_day_dedup_demo_missing_and_override(env):
    first,snap=env("CLOSED","NORMAL");assess(first,snap,True)
    later,ss=env("NORMAL","CLOSED",at=AT+timedelta(hours=2));assess(later,ss,True)
    calm,ss=env("NORMAL","CLOSED",day="2024-01-03");assess(calm,ss,False)
    demo,ss=env("CLOSED","CLOSED",day="2024-01-04",demo=True);assess(demo,ss,True)
    missing,ss=env(day="2024-01-05");assess(missing,ss,False,False)
    pending,ss=env(day="2024-01-06")
    v=feedback.statistics()
    assert v["manager"]["confusion"]==dict(true_positive=1,true_negative=1,false_alarm=0,missed_disruption=0)
    assert v["recommendation"]["confusion"]==dict(true_positive=0,true_negative=0,false_alarm=1,missed_disruption=1)
    assert v["eligible_count"]==2 and v["excluded_count"]==4
    assert v["manager"]["weighted_loss"]==0 and v["recommendation"]["weighted_loss"]==6
    assert v["agreement"]["count"]==0 and v["confirmed_operating_decisions"]["multiclass_accuracy"] is None
    assert v["override_comparisons"]["override improved weather classification"]==2
    assert feedback.statistics()["id"]==v["id"]
    assert feedback.statistics(1,10)["id"]!=v["id"]
    with db.session() as s:
        assert s.exec(select(DecisionReview)).all()==[]


def test_completed_day_and_dst_and_assessment_idempotency(env):
    d,snap=env(day="2024-03-10")
    start,end=past_decisions.day_window("2024-03-10",FAC.timezone)
    assert (end-start).total_seconds()==23*3600
    assert not feedback.record_assessment(d,snap,outcome(),start)["eligible"]
    a=feedback.record_assessment(d,snap,outcome(),end)
    b=feedback.record_assessment(d,snap,outcome(),end)
    assert a==b and len(feedback.detail(d.id)["assessments"])==2
    start,end=past_decisions.day_window("2024-11-03",FAC.timezone)
    assert (end-start).total_seconds()==25*3600
    assert feedback.measures([])["false_negative_rate"]["rate"] is None


def test_refresh_explicit_cached_no_auto_ai(env,monkeypatch):
    d,snap=env()
    calls=[]
    async def observed(*args,**kw): calls.append(1);return outcome()
    monkeypatch.setattr(past_decisions,"observed_outcome",observed)
    async def forbidden(*args):raise AssertionError("No automatic AI")
    monkeypatch.setattr(past_decisions,"review_due",forbidden)
    c=TestClient(app)
    c.get("/api/past-decisions")
    assert c.post(f"/api/decisions/{d.id}/grade/refresh").status_code==200
    assert c.post(f"/api/decisions/{d.id}/grade/refresh").status_code==200 and len(calls)==1
    d,snap=env(day="2099-01-02")
    assert c.post(f"/api/decisions/{d.id}/grade/refresh").status_code==409


def test_analysis_deidentified_bounded_and_cached(env,monkeypatch):
    from ai import feedback as ai
    d,snap=env();assess(d,snap,True)
    feedback.annotate(d.id,"Private Manager","Keep private@example.test safe")
    monkeypatch.setattr(settings,"model_provider","akamai");monkeypatch.setattr(settings,"akamai_api_key","dummy")
    calls=[]
    async def model(system,user,*args):
        assert "Private Manager" not in user and "private@example.test" not in user and "decision_id" not in user
        calls.append(user)
        return json.dumps({"findings":[{"evidence_key":"eligible_count","text":"The eligible sample is small."}],"proposals":[]}),{"tokens":20}
    monkeypatch.setattr(ai,"_akamai_chat",model)
    first=asyncio.run(feedback.analyze("Manager"));second=asyncio.run(feedback.analyze("Manager"))
    assert first==second and first["source"]=="akamai" and len(calls)==1
    assert feedback.statistics()["id"]==first["metric_id"]


@pytest.mark.parametrize("draft",[
    {"findings":[{"evidence_key":"eligible_count","text":"Accuracy is 99.999%."}],"proposals":[]},
    {"findings":[{"evidence_key":"fabrication","text":"Office closure verified."}],"proposals":[]},
    {"findings":[],"proposals":[{"category":"weather","path":"rules.wind.fcst_gust_warning.value","value":1,"rationale":"Change official criteria"}]},
])
def test_untrusted_ai_falls_back_without_policy_change(env,monkeypatch,draft):
    from ai import feedback as ai
    d,snap=env();assess(d,snap,True)
    monkeypatch.setattr(settings,"model_provider","akamai");monkeypatch.setattr(settings,"akamai_api_key","dummy")
    async def model(*args):return json.dumps(draft),{"tokens":20}
    monkeypatch.setattr(ai,"_akamai_chat",model)
    result=asyncio.run(feedback.analyze("Manager"))
    assert result["source"]=="template" and not result["validation"]["ok"] and not result["proposals"]
    assert policy.overview()["proposals"]==[]


def change():
    p=next(p for p in policy.parameters(load_thresholds()) if p["category"]=="weather")
    return {"path":p["path"],"value":p["min"] if p["current"] != p["min"] else p["max"]}


def test_policy_bounds_official_guard_and_readiness_validation(env):
    th=load_thresholds()
    with pytest.raises(HTTPException):policy.validate_changes(th,"weather",[{"path":"rules.wind.fcst_gust_warning.value","value":1}])
    with pytest.raises(HTTPException):policy.validate_changes(th,"weather",[{"path":change()["path"],"value":float("nan")}])
    with pytest.raises(HTTPException):policy.validate_changes(th,"timing",[{"path":"timing.winter_road_recovery_hours","value":1.5}])
    cand=policy.candidate(th,"weather",[change()],"test")
    assert [r for r in cand.rules if r.basis=="official"]==[r for r in th.rules if r.basis=="official"]
    p=policy.propose("Manager","readiness",[{"path":"readiness.red_within_hours","value":3}],"Test readiness change")
    result=policy.evaluate_report(p,[],{},None)
    assert result["status"]=="rejected" and "Independent" in result["reason"] and result["test_status"].startswith("Skipped")


def validated_proposal():
    p=policy.propose("Manager","weather",[change()],"Lower policy cutoff for validation")
    with db.session() as s:
        policy.event(s,p["id"],"Test validator","validated",{"report":{"status":"validated"}});s.commit()
    return policy.get(p["id"])


def test_approval_activation_auth_stale_version_atomic_reload_and_rollback(env):
    baseline=load_thresholds()
    p=validated_proposal();c=TestClient(app);url=f"/api/policies/{p['id']}"
    body={"actor":"Manager","version":p["version"]}
    assert c.post(url+"/activate",json=body,headers={"X-Threshold-Admin-Token":"manager-secret"}).status_code==409
    assert c.post(url+"/approve",json=body).status_code==403
    headers={"X-Threshold-Admin-Token":"manager-secret"}
    approved=c.post(url+"/approve",json=body,headers=headers).json();assert approved["status"]=="approved"
    assert c.post(url+"/activate",json=body,headers=headers).status_code==409
    active=c.post(url+"/activate",json={**body,"version":approved["version"]},headers=headers).json()
    assert active["status"]=="active" and load_thresholds().sha256==active["candidate"]["sha256"]
    assert c.post(url+"/activate",json={**body,"version":active["version"]},headers=headers).status_code==409
    db.set_engine(db.make_engine(f"sqlite:///{settings.db_path}"))  # server restart observes persisted policy
    assert load_thresholds().sha256==active["candidate"]["sha256"]
    assert c.post(url+"/rollback",json={**body,"version":active["version"]},headers=headers).json()["status"]=="rolled_back"
    assert load_thresholds().model_dump()==baseline.model_dump()


def test_stale_incumbent_and_restart_cancel_evaluation(env):
    first=validated_proposal();second=validated_proposal()
    first=policy.approve(first["id"],"Manager",first["version"]);policy.activate(first["id"],"Manager",first["version"])
    with pytest.raises(HTTPException):policy.approve(second["id"],"Manager",second["version"])
    p=policy.propose("Manager","weather",[change()],"New evaluation request")
    with db.session() as s:policy.event(s,p["id"],"Manager","evaluating");s.commit()
    policy.recover()
    assert policy.get(p["id"])["status"]=="rejected"


def test_full_engine_rerun_pure_and_future_inputs_rejected(env):
    from adapters.base import NormalizedInput,Point
    th=load_base_thresholds()
    snap={"facility":FAC.model_dump(mode="json"),"as_of":AT.isoformat(),"inputs":[],"sources":[]}
    inp=NormalizedInput(id="obs.temp_f",kind="series",role="observation",metric="temp_f",unit="degF",series=[Point(t=AT-timedelta(minutes=15),v=20)],source="Saved observation",source_url="https://example.test",fetched_at=AT,source_time=AT-timedelta(minutes=15))
    snap["inputs"]=[inp.model_dump(mode="json")]
    assert policy.safe_inputs(snap)
    inp.series[0].t=AT+timedelta(hours=1);snap["inputs"]=[inp.model_dump(mode="json")]
    assert not policy.safe_inputs(snap)
    snap["inputs"]=[]
    result=policy.rerun([{"day":"2024-01-02","observed":False,"snapshot":snap,"hazard":"none"}],th)
    assert result[0]["posture"]=="NORMAL" and not result[0]["prediction"]
    assert policy.overview()["activation"] is None


def test_purging_and_test_labels_never_select(env,monkeypatch):
    p=policy.propose("Manager","weather",[change()],"Test independent validation selection")
    def rows():
        return [{"day":(datetime(2021,2,1)+timedelta(days=i)).date().isoformat(),"observed":i%2==0,"hazard":"winter","artifact_sha":str(i),"evaluation_id":str(i)} for i in range(40)] + [{"day":"2024-01-02","observed":True,"hazard":"winter","artifact_sha":"test","evaluation_id":"test"}]
    def rerun(rs,th):
        candidate=th.sha256==p["candidate"]["sha256"]
        return [{**r,"prediction":r["observed"] if candidate else False,"posture":"NORMAL","readiness":"WHITE","confidence":"medium"} for r in rs]
    monkeypatch.setattr(policy,"rerun",rerun)
    a=policy.evaluate_report(p,rows(),{},None);rs=rows();rs[-1]["observed"]=False
    b=policy.evaluate_report(p,rs,{},None)
    assert a["status"]==b["status"]=="validated" and a["scores"]["validation"]==b["scores"]["validation"]
    storm=[{"day":(datetime(2020,12,27)+timedelta(days=i)).date().isoformat(),"observed":True} for i in range(11)]
    splits,purged=policy.partitions(storm,"forecast");assert len(purged)==11 and not any(splits.values())


def test_cloud_feedback_integrity_outage_retry_and_backup_restore(env,tmp_path,monkeypatch):
    class FakeBucket:
        def __init__(self): self.objects = {}; self.fail = False
        def put(self, key, data, content_type):
            if self.fail: raise ConnectionError("Unavailable")
            self.objects[key] = data
        def get(self, key): return self.objects.get(key)
    d,snap=env();feedback.annotate(d.id,"Manager","Keep staff safe");assess(d,snap,True)
    past_decisions.add_manager_review(d.id,"Manager","good_call","Observed severe weather")
    proposed=validated_proposal()
    approved=policy.approve(proposed["id"],"Manager",proposed["version"])
    activated=policy.activate(approved["id"],"Manager",approved["version"])
    asyncio.run(feedback.analyze("Manager"))
    metric=feedback.statistics()
    bucket=FakeBucket();storage.set_bucket(bucket)
    monkeypatch.setattr(storage,"_snapshot_files",lambda row:[])
    bucket.fail=True;asyncio.run(storage.sync_once());assert storage.status()["last_error"]
    bucket.fail=False;asyncio.run(storage.sync_once());assert storage.status()["last_error"] is None
    keys=[k for k in bucket.objects if k.startswith("feedback/") and not k.startswith("feedback/catalog/")]
    assert all(any(k.startswith("feedback/"+name+"/") for k in keys) for name in ("intentions","reviews","assessments","metrics","analyses","policy-proposals","policy-events","policy-activations"))
    for k in keys:
        row=json.loads(bucket.objects[k]);integrity=row.pop("integrity_sha256")
        assert hashlib.sha256(storage._json(row)).hexdigest()==integrity
    assert asyncio.run(storage.sync_once())==0
    restored=db.make_engine(f"sqlite:///{tmp_path/'restored.db'}")
    # Verify SQLite backup includes all private feedback schema and values.
    (tmp_path/'copy.db').write_bytes(storage._backup_bytes())
    copy=db.make_engine(f"sqlite:///{tmp_path/'copy.db'}")
    db.set_engine(copy);assert feedback.statistics()["id"]==metric["id"]
    assert feedback.detail(d.id)["intentions"][0]["objective"]=="Keep staff safe"
    assert load_thresholds().sha256==activated["candidate"]["sha256"]
    copy.dispose();restored.dispose()


def test_disputed_outcome_excluded_until_versioned_resolution(env):
    d,snap=env();assess(d,snap,False)
    c=TestClient(app);url=f"/api/decisions/{d.id}/grade"
    body={"actor":"Manager","verdict":"insufficient_evidence","observed_evidence_status":"disputed","note":"Station record may be incomplete"}
    r=c.post(url,json=body);assert r.status_code==201
    metric=feedback.statistics()
    assert metric["eligible_count"]==0 and metric["excluded"]["Observed evidence disputed by manager; resolution required"]==1
    assert feedback.detail(d.id)["assessments"][0]["outcome"]["severe_impact"] is False
    assert c.post(url,json={**body,"observed_evidence_status":"not_disputed","expected_id":r.json()["id"],"correction_reason":"Archive coverage checked"}).status_code==201
    assert feedback.statistics()["eligible_count"]==1


def test_bracket_changes_are_separate_from_weather_accuracy(env):
    th=load_base_thresholds()
    high=policy.candidate(th,"confidence",[{"path":"confidence.high_min","value":.9}],"confidence-test")
    assert th.rules==high.rules and high.raw["confidence_brackets"]["high_min"]==.9
    from engine.confidence import compute
    from engine.features import extract
    from engine.posture import horizon_end
    ctx=extract([],AT,[],horizon_end(AT,FAC,th.timing),FAC.timezone)
    left=compute([],[],ctx,[],{},"backtest")
    right=compute([],[],ctx,[],{},"backtest",high.raw["confidence_brackets"])
    assert left.score==right.score  # changing labels does not manufacture evidence or improve prediction


def test_provider_failure_and_malformed_json_return_template(env,monkeypatch):
    from ai import feedback as ai
    d,snap=env();assess(d,snap,True)
    monkeypatch.setattr(settings,"model_provider","akamai");monkeypatch.setattr(settings,"akamai_api_key","dummy")
    async def failure(*args):raise TimeoutError()
    monkeypatch.setattr(ai,"_akamai_chat",failure)
    assert asyncio.run(ai.explain(feedback.statistics()))["fallback_reason"]=="TimeoutError"
    async def malformed(*args):return 'not json',{"tokens":2}
    monkeypatch.setattr(ai,"_akamai_chat",malformed)
    assert asyncio.run(ai.explain(feedback.statistics()))["source"]=="template"
    assert policy.overview()["activation"] is None


def test_simultaneous_inference_is_claimed_once(env,monkeypatch):
    from ai import feedback as ai
    d,snap=env();assess(d,snap,True)
    monkeypatch.setattr(settings,"model_provider","akamai");monkeypatch.setattr(settings,"akamai_api_key","dummy")
    async def scenario():
        gate=asyncio.Event();started=asyncio.Event();calls=[]
        async def model(*args):
            calls.append(1);started.set();await gate.wait()
            return '{"findings":[],"proposals":[]}',{"tokens":2}
        monkeypatch.setattr(ai,"_akamai_chat",model)
        first=asyncio.create_task(feedback.analyze("Manager"));await started.wait()
        second=await feedback.analyze("Other manager")
        assert second["status"]=="pending"
        gate.set();result=await first
        assert result["source"]=="akamai" and len(calls)==1
    asyncio.run(scenario())


def test_second_activation_and_multi_step_rollback(env):
    base=load_thresholds()
    first=validated_proposal();first=policy.approve(first["id"],"Manager",first["version"])
    first=policy.activate(first["id"],"Manager",first["version"])
    p=next(p for p in policy.parameters(load_thresholds()) if p["path"]==first["changes"][0]["path"])
    # Bounds remain anchored to the official source registry, not successively halved.
    assert p["min"]==next(p for p in policy.parameters(base) if p["path"]==first["changes"][0]["path"])["min"]
    with pytest.raises(HTTPException):policy.validate_changes(load_thresholds(),"weather",[{"path":p["path"],"value":p["min"]-.01}])
    second=policy.propose("Manager","weather",[{"path":p["path"],"value":p["max"]}],"Test second independent change")
    with db.session() as s:policy.event(s,second["id"],"Test validator","validated");s.commit()
    second=policy.get(second["id"]);second=policy.approve(second["id"],"Manager",second["version"]);second=policy.activate(second["id"],"Manager",second["version"])
    policy.rollback(second["id"],"Manager",second["version"])
    assert load_thresholds().sha256==first["candidate"]["sha256"]
    restored=policy.get(first["id"]);assert restored["status"]=="active"
    policy.rollback(first["id"],"Manager",restored["version"])
    assert load_thresholds().sha256==base.sha256


def test_observed_outcome_requires_coverage_and_excludes_next_day(env,monkeypatch):
    from engine import outcomes
    start,end=past_decisions.day_window("2024-03-10",FAC.timezone)
    async def lsrs(*args):return [],"https://example.test/lsrs"
    rows=[{"utc_valid":(start+timedelta(hours=h,minutes=5)).isoformat(),"tmpf":30,"sknt":5,"gust":10,"raw":"METAR AO2 SLP123","wxcodes":""} for h in range(23)]
    rows.append({"utc_valid":end.isoformat(),"tmpf":30,"sknt":100,"gust":100,"raw":"METAR AO2 SLP123","wxcodes":"FZRA"})
    async def obs(*args,**kw):return [r for r in rows if datetime.fromisoformat(r["utc_valid"])<end],AT
    monkeypatch.setattr(outcomes,"fetch_lsrs",lsrs);monkeypatch.setattr(outcomes,"fetch_obhistory",obs)
    result=asyncio.run(outcomes.observed_outcome(FAC,start,end))
    assert result["coverage"]["complete"] and result["coverage"]["expected_hours"]==23 and not result["severe_impact"]
    rows[:]=rows[:1]
    result=asyncio.run(outcomes.observed_outcome(FAC,start,end))
    assert not result["coverage"]["complete"]


def test_real_engine_candidate_comparison_on_synthetic_forecasts(env):
    from adapters.base import NormalizedInput, Point
    rows=[]
    day=datetime(2021,2,1,tzinfo=timezone.utc)
    while len(rows)<40:
        if day.weekday()<5:
            local=day.replace(hour=10)
            actual=len(rows)%2==0
            inp=NormalizedInput(id="fcst.wind_gust_mph",kind="series",role="forecast",metric="wind_gust_mph",unit="mph",
                                series=[Point(t=local+timedelta(hours=4),v=40 if actual else 10)],source="Synthetic saved forecast",
                                source_url="https://example.test",fetched_at=local,source_time=local-timedelta(hours=3))
            rows.append({"day":day.date().isoformat(),"observed":actual,"hazard":"wind","artifact_sha":str(len(rows)),
                         "evaluation_id":str(len(rows)),"snapshot":{"as_of":local.isoformat(),"facility":FAC.model_dump(mode="json"),"sources":[],"inputs":[inp.model_dump(mode="json")]}})
        day+=timedelta(days=1)
    p=policy.propose("Manager","weather",[{"path":"rules.wind.fcst_gust_advisory.value","value":35}],"Test lower policy wind cutoff")
    result=policy.evaluate_report(p,rows,{},None)
    assert result["status"]=="validated"
    val=result["scores"]["validation"]
    assert val["incumbent"]["confusion"]["missed_disruption"]==20
    assert val["candidate"]["confusion"]["true_positive"]==20
    assert val["candidate"]["weighted_loss"]<val["incumbent"]["weighted_loss"]
    assert policy.overview()["activation"] is None


def test_frozen_cohort_integrity_never_rebuilt(env,tmp_path,monkeypatch):
    from app import risk_experiment
    path=tmp_path/'frozen.json';monkeypatch.setattr(risk_experiment,'manifest_path',lambda:path)
    with pytest.raises(ValueError,match='unavailable'):policy.cohort_rows('baseline')
    path.write_text(json.dumps({'n':7470,'entries':[],'cohort_sha':'tampered'}))
    with pytest.raises(ValueError,match='identity'):policy.cohort_rows('baseline')
    assert json.loads(path.read_text())['cohort_sha']=='tampered'


def test_single_class_metrics_never_invent_denominators():
    m=feedback.measures([(False,False)])
    assert m['accuracy']==1 and m['specificity']==1 and m['false_positive_rate']['rate']==0
    assert m['balanced_accuracy'] is None and m['precision'] is None and m['recall'] is None
    assert m['false_negative_rate']['n']==0 and m['false_negative_rate']['rate'] is None
