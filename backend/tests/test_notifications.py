"""Notification routing, review, durable scheduling and simulation boundary."""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app import db, notifications as n
from app.models import Decision, NotificationAudit, NotificationPackage, Snapshot
from app.routers.notifications import Action, Edit

NOW = datetime(2026, 10, 12, 9, tzinfo=timezone.utc)  # 04:00 Central
FAC = {"id": "F", "name": "Demo facility", "timezone": "America/Chicago", "hours": {"open": "07:30"}}


def employee(id="onsite", **extra):
    return {"id": id, "name": id, "assigned_facility": "F", "this_week_location": "F",
            "essential": False, "teleworking_today": False, "telework_eligible": True,
            "contact_channels": ["sms", "email"], **extra}


@pytest.fixture
def env(tmp_path, monkeypatch):
    old = db._engine
    engine = db.make_engine(f"sqlite:///{tmp_path / 'notify.db'}")
    db.set_engine(engine)
    monkeypatch.setattr(n, "CONTACT_FILE", tmp_path / "contacts.json")
    employees = [employee(), employee("essential", essential=True), employee("remote", teleworking_today=True)]
    monkeypatch.setattr(n, "load_employees", lambda: employees)
    snap = {"snapshot_id": "snapshot", "facility": FAC, "mode": "live", "posture": {"decision_day": "2026-10-12"},
            "hazards": {"winter": {"level": "extreme"}}}
    monkeypatch.setattr(n.snapshots, "get", lambda sid: snap)
    monkeypatch.setattr(n, "weather_wording", template)
    monkeypatch.setattr("app.routers.notifications.get_facility", lambda facility_id=None: SimpleNamespace(**FAC))
    with db.session() as s:
        values = {field: "{}" for field in Snapshot.model_fields if field.endswith("_json")}
        s.add(Snapshot(**values, snapshot_id="snapshot", facility_id="F", as_of=NOW, created_at=NOW, mode="live",
                       posture="CLOSED", opm_label="Closed", confidence="high", confidence_score=1,
                       thresholds_version="v1", thresholds_sha256="hash", model_id="none", prompt_version="v1", content_sha256="hash"))
        s.commit()
    n.set_clock(NOW, "Test manager")
    yield SimpleNamespace(employees=employees, snap=snap, engine=engine)
    db.set_engine(old)
    engine.dispose()


async def template(snap):
    return "Weather assessment: winter hazard.", "Template (no model)", {
        "provider": "template", "fallback_used": True, "requests": [], "failures": []}


def decision(posture="CLOSED", **extra):
    with db.session() as s:
        d = Decision(snapshot_id="snapshot", facility_id="F", decided_by="Manager", decision_posture=posture,
                     recommended_posture="CLOSED", agreed_with_recommendation=posture == "CLOSED", decided_at=NOW, **extra)
        s.add(d); s.commit(); s.refresh(d)
        return d.id


def package():
    return asyncio.run(n.create(decision()))


def action(p):
    return Action(version=p["version"], actor="Test manager")


def approve_all(p):
    for g in p["groups"]:
        p = n.approve(p["id"], g["id"], action(p))
    return p


def edit(p, g, **extra):
    return n.edit(p["id"], g["id"], Edit(version=p["version"], actor="Test manager",
                 sms_intro=g["sms_intro"], email_intro=g["email_intro"], **extra))


def read(pid):
    with db.session() as s:
        return json.loads(s.get(NotificationPackage, pid).state_json)


def test_routing_effective_assignment_essential_telework_and_schedules():
    emps = [employee(), employee("essential", essential=True), employee("remote", teleworking_today=True, work_start="08:00"),
            employee("detail-in", assigned_facility="OTHER"), employee("detail-out", this_week_location="detail:OTHER"),
            employee("travel", this_week_location="travel:DC"), employee("unrelated", assigned_facility="OTHER", this_week_location="OTHER"),
            employee("off", workdays=[1]), employee("leave", telework_eligible=False)]
    groups, excluded = n.resolve(emps, FAC, "2026-10-12", "CLOSED", "07:30", NOW)
    by = {r["id"]: (g, r) for g in groups for r in g["recipients"]}
    assert by["essential"][0]["kind"] == "essential"
    assert "remain in force" in by["essential"][0]["instruction"]
    assert by["detail-in"][0]["kind"] == "onsite"
    assert by["detail-out"][0]["kind"] == by["travel"][0]["kind"] == "awareness"
    assert by["remote"][1]["channels"] == ["email"]
    assert by["remote"][1]["due_at"] == "2026-10-12T13:00:00+00:00"
    assert by["onsite"][1]["due_at"] == NOW.isoformat()
    assert "leave" in by["leave"][0]["instruction"]
    assert {e["id"] for e in excluded} == {"unrelated", "off"}


def test_timezone_fallback_past_schedule_and_normal():
    groups, _ = n.resolve([employee("remote", teleworking_today=True)], FAC, "2026-10-12", "CLOSED", "07:30", NOW)
    assert groups[0]["recipients"][0]["due_at"] == "2026-10-12T12:30:00+00:00"
    assert n.at_local("2026-12-14", "07:30", FAC["timezone"]).hour == 13  # CST
    later = datetime(2026, 10, 12, 15, tzinfo=timezone.utc)
    groups, _ = n.resolve([employee("remote", teleworking_today=True)], FAC, "2026-10-12", "CLOSED", "07:30", later)
    assert groups[0]["recipients"][0]["due_at"] == later.isoformat()
    assert not n.resolve([employee()], FAC, "2026-10-12", "NORMAL", "07:30", NOW)[0]
    assert n.resolve([employee()], FAC, "2026-10-12", "NORMAL", "07:30", NOW, "CLOSED")[0]


def test_draft_never_sends_requires_decision_and_all_approvals(env):
    with pytest.raises(HTTPException): asyncio.run(n.create(999))
    p = package()
    assert p["messages"] == []
    with pytest.raises(HTTPException): n.dispatch(p["id"], action(p))
    p = n.approve(p["id"], p["groups"][0]["id"], action(p))
    with pytest.raises(HTTPException): n.dispatch(p["id"], action(p))


def test_edit_clears_approval_stale_version_rejected(env):
    p = approve_all(package())
    old = action(p)
    p = edit(p, p["groups"][0], scenario="failure")
    assert not p["groups"][0]["approved"]
    with pytest.raises(HTTPException) as e: n.approve(p["id"], p["groups"][0]["id"], old)
    assert e.value.status_code == 409
    with pytest.raises(HTTPException): n.dispatch(p["id"], action(p))


def test_duplicate_creation_send_and_durable_schedule(env):
    p = package()
    assert asyncio.run(n.create(p["decision_id"]))["id"] == p["id"]
    p = approve_all(p)
    req = action(p)
    sent = n.dispatch(p["id"], req)
    assert n.dispatch(p["id"], req)["messages"] == sent["messages"]
    assert len({m["id"] for m in sent["messages"]}) == len(sent["messages"])
    assert any(m["status"] == "scheduled" for m in sent["messages"])
    assert all(m["address"].startswith("synthetic:") for m in sent["messages"])
    # Fresh engine simulates restart: worker reads durable rows and clock, no in-memory queue.
    replacement = db.make_engine(str(env.engine.url))
    db.set_engine(replacement)
    n.set_clock(datetime(2026, 10, 12, 13, tzinfo=timezone.utc), "Manager")
    complete = read(p["id"])
    assert all(m["status"] == "simulated_sent" for m in complete["messages"])
    n.tick()
    assert all(len(m["attempts"]) == 1 for m in read(p["id"])["messages"])
    replacement.dispose()
    db.set_engine(env.engine)


def test_failure_retry_and_delay(env):
    p = package()
    p = edit(p, p["groups"][0], scenario="failure")
    p = edit(p, p["groups"][1], scenario="delay")
    p = n.dispatch(p["id"], action(approve_all(p)))
    failed = next(m for m in p["messages"] if m["status"] == "simulated_failed")
    p = n.retry(p["id"], failed["id"], action(p))
    retried = next(m for m in p["messages"] if m["id"] == failed["id"])
    assert retried["status"] == "simulated_sent" and len(retried["attempts"]) == 2
    with pytest.raises(HTTPException): n.retry(p["id"], failed["id"], action(p))
    n.set_clock(datetime(2026, 10, 12, 9, 6, tzinfo=timezone.utc), "Manager")
    assert not any(m["status"] == "delayed" for m in read(p["id"])["messages"])


def test_new_decision_cancels_old_pending_and_prevents_stale_dispatch(env):
    old = n.dispatch((p := approve_all(package()))["id"], action(p))
    newer = approve_all(asyncio.run(n.create(decision("TELEWORK"))))
    assert read(old["id"])["status"] == "dispatched"  # Draft/approval alone does not cancel.
    n.dispatch(newer["id"], action(newer))
    old = read(old["id"])
    assert old["status"] == "superseded"
    assert any(m["status"] == "canceled" for m in old["messages"])
    assert any(m["status"] == "simulated_sent" for m in old["messages"])
    with pytest.raises(HTTPException): n.dispatch(old["id"], action(old))


def test_local_test_contacts_separate_and_audit_immutable(env):
    n.CONTACT_FILE.write_text(json.dumps({"contacts": [{"name": "Test", "channel": "email", "address": "test@example.com"}]}))
    p = package()
    cid = n.contacts()[0]["id"]
    p = edit(p, p["groups"][0], test_contacts=[cid])
    p = n.dispatch(p["id"], action(approve_all(p)))
    test = [m for m in p["messages"] if not m["synthetic"]]
    assert len(test) == 1 and test[0]["address"] == "test@example.com"
    assert test[0]["recipient_id"] == cid
    with db.session() as s:
        rows = s.exec(select(NotificationAudit).where(NotificationAudit.package_id == p["id"])).all()
        assert {r.action for r in rows} >= {"draft_created", "group_approved", "dispatch_authorized", "delivery_attempt"}
        with pytest.raises(IntegrityError):
            s.delete(rows[0]); s.commit()


def test_api_validation_and_overview(env):
    from app.main import app
    client = TestClient(app)
    assert client.post("/api/notifications/packages", json={"decision_id": 999}).status_code == 404
    assert client.put("/api/notifications/clock", json={"now": "invalid", "actor": "Manager"}).status_code == 422
    assert client.put("/api/notifications/clock", json={"now": "2026-10-12T04:00:00", "actor": "Manager"}).status_code == 422
    assert client.post("/api/notifications/packages", json={"decision_id": decision(), "fallback_start": "99:00"}).status_code == 422
    r = client.post("/api/notifications/packages", json={"decision_id": decision()})
    assert r.status_code == 200
    data = client.get("/api/notifications").json()
    assert data["provider"] == "simulation" and data["demo_clock"]
    assert data["packages"][0]["groups"][0]["previews"]["sms"]


def test_no_credentials_template_and_ai_excludes_contacts(env, monkeypatch):
    # Restore actual function shadowed by fixture to verify real no-provider path below.
    from importlib import util
    spec = util.spec_from_file_location("notify_copy", n.__file__)
    copy = util.module_from_spec(spec); spec.loader.exec_module(copy)
    async def no_model(system, user):
        return None, "none", {"provider": "template", "requests": [], "failures": []}
    monkeypatch.setattr(copy, "hazard_sentence", no_model)
    wording, source, _ = asyncio.run(copy.weather_wording(env.snap))
    assert source == "Template (no model)" and "winter" in wording
    captured = []
    from ai import agent
    monkeypatch.setattr(agent.settings, "model_provider", "akamai")
    monkeypatch.setattr(agent.settings, "akamai_api_key", "test-team-key")
    async def unsafe_model(system, user, *args):
        captured.append(user)
        return json.dumps({"explanation": "Close the facility and do not report."}), {
            "provider": "akamai", "model": "hackathon-chat", "usage": None}
    monkeypatch.setattr(agent, "_akamai_chat", unsafe_model)
    monkeypatch.setattr(copy, "hazard_sentence", agent.hazard_sentence)
    _, source, inference = asyncio.run(copy.weather_wording({**env.snap, "employees": [{"email": "private@example.com"}]}))
    assert source == "Template (AI unavailable or draft rejected)"
    assert inference["provider"] == "template" and len(inference["requests"]) == 1
    assert "private@example.com" not in captured[0]


def test_unchanged_instructions_not_resent_and_dated_assignment(env):
    p = approve_all(package())
    n.dispatch(p["id"], action(p))
    fresh = asyncio.run(n.create(decision()))
    assert len(fresh["groups"]) == 4
    assert not any(g["recipient_ids"] for g in fresh["groups"])
    assert all("unchanged" in r["selection_note"] for g in fresh["groups"] for r in g["recipients"])
    e = employee("dated", assignments=[{"start": "2026-10-12", "end": "2026-10-13", "this_week_location": "detail:OTHER"}])
    groups, _ = n.resolve([e], FAC, "2026-10-12", "CLOSED", "07:30", NOW)
    assert groups[0]["kind"] == "awareness"


def test_invalid_test_contact_and_backward_clock_rejected(env):
    p = package()
    with pytest.raises(HTTPException): edit(p, p["groups"][0], test_contacts=["missing"])
    with pytest.raises(HTTPException): n.set_clock(datetime(2026, 10, 12, 8, tzinfo=timezone.utc), "Manager")


def test_followup_select_multiple_recipients_and_preserve_sent_history(env):
    env.employees.append(employee("second"))
    p = approve_all(package())
    p = n.dispatch(p["id"], action(p))
    original = [m.copy() for m in p["messages"] if m["status"] == "simulated_sent"]
    p = n.followup(p["id"], action(p))
    assert p["status"] == "draft" and not any(g["approved"] for g in p["groups"])
    for g in list(p["groups"]):
        p = edit(p, g, recipient_ids=["onsite", "second"] if g["id"] == "onsite-telework" else [])
    p = approve_all(p)
    p = n.dispatch(p["id"], action(p))
    new = [m for m in p["messages"] if ':v2:' in m["id"]]
    assert {m["recipient_id"] for m in new} == {"onsite", "second"}
    assert len(new) == 4
    assert all(m in p["messages"] for m in original)
    assert all("replaces" in m["body"] for m in new)


def test_explicit_manual_update_can_create_groups_for_unchanged_decision(env):
    p = approve_all(package())
    n.dispatch(p["id"], action(p))
    did = decision()
    empty = asyncio.run(n.create(did))
    assert len(empty["groups"]) == 4
    assert not any(g['recipient_ids'] for g in empty['groups'])
    group = next(g for g in empty['groups'] if g['id'] == 'onsite-telework')
    manual = edit(empty, group, recipient_ids=[r['id'] for r in group['recipients']])
    assert manual['groups'][0]['recipient_ids']
    assert not manual['messages'] and not any(g['approved'] for g in manual['groups'])



def test_one_action_reviews_all_groups_then_sends(env):
    from app.main import app
    client = TestClient(app)
    p = package()
    groups = [{"id":g["id"], "sms_intro":"Reviewed weather", "email_intro":"Reviewed weather details",
               "recipient_ids":[r["id"] for r in g["recipients"]]} for g in p["groups"]]
    response = client.post(f"/api/notifications/packages/{p['id']}/review", json={
        "version":p["version"], "actor":"Manager", "groups":groups, "approve_and_send":True})
    assert response.status_code == 200
    sent = response.json()
    assert sent["status"] == "dispatched" and sent["messages"]
    assert all(g["approved"] for g in sent["groups"])


def test_real_tests_require_configuration_allowlist_and_approval(env, monkeypatch):
    from app import real_delivery as real
    from app.routers.notifications import RealTest
    n.CONTACT_FILE.write_text(json.dumps({"contacts":[{"channel":"email","address":"tester@example.com"}]}))
    p = approve_all(package())
    req = RealTest(version=p["version"], actor="Manager", group_id=p["groups"][0]["id"],
                   contact_ids=[n.contacts()[0]["id"]], request_id="test-request-1")
    monkeypatch.setattr(real, "readiness", lambda: {"email":False,"sms":False})
    with pytest.raises(HTTPException): real.send_tests(p["id"],req)
    monkeypatch.setattr(real, "readiness", lambda: {"email":True,"sms":True})
    calls=[]
    monkeypatch.setattr(real, "deliver", lambda c,b: calls.append((c,b)) or {"status":"provider_accepted", "detail":"Accepted, not confirmed"})
    result=real.send_tests(p["id"],req)
    assert len(calls)==1 and calls[0][1].startswith("TEST ONLY")
    assert result["messages"][0]["status"]=="provider_accepted"
    assert real.send_tests(p["id"],req)==result and len(calls)==1
    req.request_id="test-request-2"; req.version=read(p["id"])["version"]; req.contact_ids=["E001"]
    with pytest.raises(HTTPException): real.send_tests(p["id"],req)


def test_real_provider_error_is_unknown_not_success_and_not_retried(env, monkeypatch):
    from app import real_delivery as real
    from app.routers.notifications import RealTest
    n.CONTACT_FILE.write_text(json.dumps({"contacts":[{"channel":"email","address":"tester@example.com"}]}))
    p=approve_all(package())
    req=RealTest(version=p["version"],actor="Manager",group_id=p["groups"][0]["id"],contact_ids=[n.contacts()[0]["id"]],request_id="test-unknown-1")
    monkeypatch.setattr(real,"readiness",lambda:{"email":True,"sms":True})
    def broken(*args): raise TimeoutError()
    monkeypatch.setattr(real,"deliver",broken)
    result=real.send_tests(p["id"],req)
    assert result["messages"][0]["status"]=="delivery_unknown"
    assert real.send_tests(p["id"],req)==result



def test_smtp_bot_rejects_real_sms(env, monkeypatch):
    from app import real_delivery as real
    from app.routers.notifications import RealTest
    n.CONTACT_FILE.write_text(json.dumps({"contacts": [{"channel": "sms", "address": "+15555550100"}]}))
    p = approve_all(package())
    req = RealTest(version=p["version"], actor="Manager", group_id=p["groups"][0]["id"],
                   contact_ids=[n.contacts()[0]["id"]], request_id="sms-disabled")
    monkeypatch.setattr(real, "readiness", lambda: {"email": True, "sms": True})
    with pytest.raises(HTTPException, match="gateway email address"):
        real.send_tests(p["id"], req)


def test_smtp_bot_tls_and_personalized_email(env, monkeypatch):
    from app import real_delivery as real
    for key, value in {"SMTP_HOST": "smtp.example.com", "SMTP_USERNAME": "bot",
                       "SMTP_PASSWORD": "local-secret", "SMTP_FROM": "bot@example.com", "SMTP_PORT": "587"}.items():
        monkeypatch.setenv(key, value)
    calls = []
    class SMTP:
        def __init__(self, host, port, timeout):
            assert (host, port) == ("smtp.example.com", 587)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def starttls(self, context): calls.append("tls")
        def login(self, user, password): calls.append("login")
        def send_message(self, message):
            assert message["To"] == "tester@example.com"
            assert "TEST ONLY" in message["Subject"]
            assert "Hello Casey" in message.get_content()
            calls.append("sent")
            return {}
    from app import smtp_service
    monkeypatch.setattr(smtp_service.smtplib, "SMTP", SMTP)
    result = real.deliver({"channel": "email", "address": "tester@example.com"}, "TEST ONLY: Hello Casey")
    assert result["status"] == "provider_accepted"
    assert calls == ["tls", "login", "sent"]
    assert real.readiness() == {"email": True, "sms": False}


def test_gateway_submission_and_duplicates(env, monkeypatch):
    from app import real_delivery as real, smtp_service
    from app.routers.notifications import RealTest
    n.CONTACT_FILE.write_text(json.dumps({"contacts": [{"channel": "sms", "address": "+15555550100", "gateway_address": "phone@gateway.example"}]}))
    monkeypatch.setattr(smtp_service, "configured", lambda: True)
    calls = []
    monkeypatch.setattr(smtp_service, "send_email", lambda address, body: calls.append((address, body)) or {"status": "provider_accepted"})
    p = approve_all(package())
    req = RealTest(version=p["version"], actor="Manager", group_id=p["groups"][0]["id"], contact_ids=[n.contacts()[0]["id"]], request_id="gateway-test")
    result = real.send_tests(p["id"], req)
    assert calls[0][0] == "phone@gateway.example" and calls[0][1].startswith("TEST ONLY")
    assert "not confirmed" in result["messages"][0]["detail"]
    assert result["messages"][0]["gateway_address"] == "phone@gateway.example"
    assert real.send_tests(p["id"], req) == result and len(calls) == 1
    assert not real.valid_gateway("phone@gateway.example\nBcc: another@example.com")


def test_login_check_never_sends(monkeypatch):
    from app import smtp_service
    monkeypatch.setattr(smtp_service, "configured", lambda: True)
    for k,v in {"SMTP_HOST":"smtp.example.com", "SMTP_PORT":"587", "SMTP_USERNAME":"bot", "SMTP_PASSWORD":"secret"}.items():
        monkeypatch.setenv(k,v)
    class SMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def starttls(self, **kwargs): pass
        def login(self, *args): pass
        def send_message(self, *args): pytest.fail("Login check must not send")
    monkeypatch.setattr(smtp_service.smtplib, "SMTP", SMTP)
    assert smtp_service.check_connection()["status"] == "authenticated"
    def reject(*args): raise smtp_service.smtplib.SMTPAuthenticationError(535,b"secret")
    monkeypatch.setattr(SMTP, "login", reject)
    result = smtp_service.check_connection()
    assert result["status"] == "authentication_failed" and "secret" not in result["detail"]


def test_three_box_override_delivery_and_audit(env):
    p = package()
    assert len({g['decision_text'] for g in p['groups']}) == 1
    assert all(g['template'] for g in p['groups'])
    g = p['groups'][0]
    p = n.approve(p['id'], g['id'], action(p))
    p = edit(p, g, location_text='Ames · Monday', decision_text='The facility is closed.',
             instruction_text='Contact your supervisor before reporting.')
    changed = p['groups'][0]
    assert not changed['approved'] and changed['instruction_override']
    assert p['snapshot_id'] == 'snapshot' and p['posture'] == 'CLOSED'
    for channel in ['sms', 'email']:
        assert n.message_text(p, changed, channel, 'Casey') == 'Ames · Monday\nThe facility is closed.\nCasey: Contact your supervisor before reporting.'
    p = approve_all(p)
    p = n.dispatch(p['id'], action(p))
    assert any('Contact your supervisor before reporting.' in m['body'] for m in p['messages'])
    with db.session() as s:
        edits = s.exec(select(NotificationAudit).where(NotificationAudit.action == 'group_edited_approval_invalidated')).all()
        assert any('instruction_override' in a.detail_json for a in edits)


def test_empty_message_box_does_not_change_saved_draft(env):
    p = package()
    with pytest.raises(HTTPException):
        edit(p, p['groups'][0], instruction_text='   ')
    assert read(p['id'])['version'] == p['version']


def test_decision_camera_frames_are_saved_once_and_survive_restart(env, monkeypatch):
    from app import camera_archive as ca
    from app.models import DecisionCameraFrame
    from app.routers.cameras import saved_frame
    did = decision()
    with db.session() as s:
        s.add(ca.pending(s.get(Decision, did))); s.commit()
    calls = []
    async def cameras(*args, **kwargs):
        return ([{'id':'cam1','name':'Camera one','km':1,'views':[
            {'url':'older','time':'2026-10-12T08:50:00+00:00','view':0},
            {'url':'superseded-angle','time':'2026-10-12T08:40:00+00:00','view':0},
            {'url':'latest','time':'2026-10-12T08:59:00+00:00','view':1},
            {'url':'future','time':'2026-10-12T09:01:00+00:00','view':2}]},
            {'id':'cam2','name':'Camera two','km':2,'views':[{'url':'missing','time':'2026-10-12T08:59:00+00:00','view':0}]}], None)
    async def image(url): calls.append(url); return b'saved-image-bytes' if url in {'older','latest'} else None
    async def empty(*args, **kwargs): return []
    monkeypatch.setattr(ca, 'fetch_webcams', empty)
    monkeypatch.setattr(ca, 'fetch_traffic_cameras', empty)
    monkeypatch.setattr(ca,'fetch_cameras',cameras)
    monkeypatch.setattr(ca,'get_image',image)
    monkeypatch.setattr(ca,'get_facility',lambda _:SimpleNamespace(**FAC, state='IA'))
    asyncio.run(ca.capture(did,'F',NOW))
    archive = ca.saved(did)
    assert len(archive['cameras']) == 1 and len(archive['cameras'][0]['views']) == 2
    assert len(archive['unavailable']) == 1 and 'future' not in calls and 'superseded-angle' not in calls
    ca.abandon_interrupted()
    asyncio.run(ca.capture(did,'F',NOW))
    assert len(calls)==3 and ca.saved(did)==archive
    with db.session() as s:
        frames=s.exec(select(DecisionCameraFrame)).all()
        assert len(frames)==2 and all(f.image==b'saved-image-bytes' for f in frames)
        assert saved_frame(frames[0].id).body==b'saved-image-bytes'
    assert ca.saved(999)['status']=='unavailable'


def test_interrupted_camera_capture_never_fetches_new_images(env):
    from app import camera_archive as ca
    did=decision()
    with db.session() as s:
        s.add(ca.pending(s.get(Decision,did)));s.commit()
    ca.abandon_interrupted()
    assert ca.saved(did)['status']=='unavailable'


def test_live_traffic_photo_saved_without_live_links_or_stale_fallback(env, monkeypatch):
    from app import camera_archive as ca
    did=decision()
    with db.session() as s:
        s.add(ca.pending(s.get(Decision,did)));s.commit()
    async def empty(*args, **kwargs): return []
    async def traffic(*args, **kwargs):
        return ([{'id':'traffic1','name':'Near facility','kind':'traffic','km':1,
                  'stream_url':'live-stream', 'snapshot_url':'mutable-photo',
                  'views':[{'view':0,'url':'mutable-photo','time':'2026-10-12T09:01:00+00:00','label':'Live'}]}],None)
    calls=[]
    async def image(url, allow_stale=True):
        calls.append((url,allow_stale));return b'current-photo'
    monkeypatch.setattr(ca,'fetch_cameras',empty)
    monkeypatch.setattr(ca,'fetch_webcams',empty)
    monkeypatch.setattr(ca,'fetch_traffic_cameras',traffic)
    monkeypatch.setattr(ca,'get_image',image)
    monkeypatch.setattr(ca,'get_facility',lambda _:SimpleNamespace(**FAC, state='IA'))
    monkeypatch.setattr(ca.settings,'demo_mode',False)
    asyncio.run(ca.capture(did,'F',NOW))
    cam=ca.saved(did)['cameras'][0]
    assert calls==[('mutable-photo',False)]
    assert 'stream_url' not in cam and 'snapshot_url' not in cam
    assert cam['views'][0]['url'].startswith('/api/cameras/saved-frame/')
    assert cam['views'][0]['timestamp_kind']=='retrieved_at'
    assert cam['views'][0]['source_url']=='mutable-photo'
    asyncio.run(ca.capture(did,'F',NOW))
    assert len(calls)==1


def test_cancelled_capture_cleans_up_image_tasks(env, monkeypatch):
    from app import camera_archive as ca
    did=decision()
    with db.session() as s:
        s.add(ca.pending(s.get(Decision,did)));s.commit()
    async def empty(*a,**kw):return []
    async def cams(*a,**kw):
        return ([{'id':'cam','name':'cam','km':1,'views':[{'view':0,'url':'image','time':NOW.isoformat()}]}],None)
    monkeypatch.setattr(ca,'fetch_cameras',cams)
    monkeypatch.setattr(ca,'fetch_webcams',empty)
    monkeypatch.setattr(ca,'fetch_traffic_cameras',empty)
    monkeypatch.setattr(ca,'get_facility',lambda _:SimpleNamespace(**FAC, state='IA'))
    async def verify():
        started=asyncio.Event(); stopped=asyncio.Event()
        async def image(*a,**kw):
            started.set()
            try: await asyncio.Event().wait()
            finally: stopped.set()
        monkeypatch.setattr(ca,'get_image',image)
        task=asyncio.create_task(ca.capture(did,'F',NOW))
        await asyncio.wait_for(started.wait(),2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert stopped.is_set()
    asyncio.run(verify())


def test_refresh_ai_reason_preserves_routing_and_instructions_clears_approval(env, monkeypatch):
    p = package()
    p = n.approve(p['id'], p['groups'][0]['id'], action(p))
    original = [(g['instruction_text'], g['recipients'], g['location_text']) for g in p['groups']]
    async def wording(snap):
        assert snap['manager_decision'] == 'CLOSED'
        return 'Extreme winter hazards are present.', 'Powered by Akamai', {'provider': 'akamai'}
    monkeypatch.setattr(n, 'weather_wording', wording)
    updated = asyncio.run(n.regenerate(p['id'], action(p)))
    assert updated['version'] == p['version'] + 1
    assert all(not g['approved'] for g in updated['groups'])
    assert [(g['instruction_text'], g['recipients'], g['location_text']) for g in updated['groups']] == original
    assert all('Extreme winter hazards' in g['decision_text'] for g in updated['groups'])
    assert updated['messages'] == []
    with db.session() as s:
        assert any(a.action == 'ai_wording_refreshed' for a in s.exec(select(NotificationAudit)).all())
    with pytest.raises(HTTPException) as error:
        asyncio.run(n.regenerate(p['id'], action(p)))
    assert error.value.status_code == 409


@pytest.mark.parametrize('posture', list(n.LABELS))
def test_each_manager_scenario_has_its_own_prompt_and_group_instructions(env, monkeypatch, posture):
    from importlib import util
    spec = util.spec_from_file_location('scenario_notify', n.__file__)
    copy = util.module_from_spec(spec); spec.loader.exec_module(copy)
    async def model(system, user):
        data = json.loads(user)
        assert data['manager_decision'] == posture
        assert data['recommended_decision'] == 'CLOSED'
        assert copy.SCENARIO_FOCUS[posture] in system
        assert 'employees' not in data and 'contacts' not in data
        return 'Extreme winter hazards are present.', 'akamai:hackathon-chat', {'provider':'akamai', 'failures':[]}
    monkeypatch.setattr(copy, 'hazard_sentence', model)
    wording, source, _ = asyncio.run(copy.weather_wording({**env.snap, 'manager_decision':posture, 'posture':{'posture':'CLOSED'}}))
    assert 'Powered by Akamai' in source
    assert wording == 'Extreme winter hazards are present.'
    p = asyncio.run(n.create(decision(posture), include_unchanged=True))
    assert p['posture'] == posture
    for g in p['groups']:
        assert n.LABELS[posture].lower() in g['decision_text']
        assert g['instruction_text'] == n.instruction(g['kind'], posture, g['id'] != 'onsite-leave')


def test_legacy_draft_restores_missing_groups_without_selecting_them(env):
    p = package()
    missing = next(g for g in p['groups'] if g['id'] == 'onsite-telework')
    p['groups'] = [g for g in p['groups'] if g['id'] != missing['id']]
    p.pop('group_visibility_version')
    p['excluded'].extend({'id':r['id'], 'name':r['name'], 'reason':'Already notified for this date; reporting instructions unchanged'} for r in missing['recipients'])
    with db.session() as s:
        row = s.get(NotificationPackage, p['id'])
        n.store(s, row, p); s.commit()
    restored = asyncio.run(n.create(p['decision_id']))
    assert len(restored['groups']) == 4
    recovered = next(g for g in restored['groups'] if g['id'] == missing['id'])
    assert recovered['recipients'] and recovered['recipient_ids'] == []
    assert not any(g['approved'] for g in restored['groups'])
    assert not restored['messages']
    selected = edit(restored, recovered, recipient_ids=['onsite'])
    assert next(g for g in selected['groups'] if g['id'] == missing['id'])['recipient_ids'] == ['onsite']


@pytest.mark.parametrize('posture,field', [('CLOSED','notes'), ('TELEWORK','override_reason')])
def test_manager_reason_is_used_in_prompt_and_outgoing_decision(env, monkeypatch, posture, field):
    from importlib import util
    spec = util.spec_from_file_location('reason_notify', n.__file__)
    copy = util.module_from_spec(spec); spec.loader.exec_module(copy)
    reason = 'County roads remain untreated; contact lead@example.com or +19132206510.'
    async def model(system, user):
        data = json.loads(user)
        assert 'County roads remain untreated' in data['manager_reason']
        assert 'lead@example.com' not in user and '19132206510' not in user
        assert data['agreed_with_recommendation'] == (posture == 'CLOSED')
        assert 'primary emphasis' in system
        return 'Winter hazards remain significant.', 'akamai:hackathon-chat', {'provider':'akamai', 'failures':[]}
    monkeypatch.setattr(copy, 'hazard_sentence', model)
    asyncio.run(copy.weather_wording({**env.snap, 'manager_decision':posture, 'manager_reason':reason, 'manager_agreed':posture == 'CLOSED'}))
    did = decision(posture, **{field:reason})
    p = asyncio.run(n.create(did))
    for g in p['groups']:
        assert 'County roads remain untreated' in g['decision_text']
        assert 'lead@example.com' not in g['decision_text'] and '19132206510' not in g['decision_text']
        assert 'County roads remain untreated' in g['template']['decision_text']
    refreshed = asyncio.run(n.regenerate(p['id'], action(p)))
    assert all('County roads remain untreated' in g['decision_text'] for g in refreshed['groups'])
    assert not refreshed['messages']
