"""API verification of Akamai briefs, manager decisions and approval-only notifications."""
import asyncio
import json
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ai import agent, fallback
from app import db, snapshots
from app.config import settings
from app.facility import load_facility
from app.main import app


def test_brief_does_not_decide_and_manager_override_is_audited(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "model_provider", "akamai")
    monkeypatch.setattr(settings, "akamai_api_key", "test-team-key")
    monkeypatch.setattr(settings, "strands_fallback_enabled", False)
    old = db._engine
    engine = db.make_engine(f"sqlite:///{tmp_path / 'workflow.db'}")
    db.set_engine(engine)
    async def inference(provider, snap, feedback):
        return fallback.build(snap), {"provider": "akamai", "model": "hackathon-chat", "usage": {
            "input_tokens": 100, "output_tokens": 200, "total_tokens": 300}}
    monkeypatch.setattr(agent, "_run_agent", inference)
    notification_calls = []
    async def notification_inference(system, user, *args):
        notification_calls.append(user)
        assert "employees" not in user and "@" not in user
        return json.dumps({"explanation": "Extreme wind hazards are present."}), {
            "provider": "akamai", "model": "hackathon-chat", "usage": {
                "input_tokens": 10, "output_tokens": 20, "total_tokens": 30}}
    monkeypatch.setattr(agent, "_akamai_chat", notification_inference)
    try:
        with TestClient(app) as client:
            result = client.post("/api/evaluate", json={"mode": "replay", "as_of": "2020-08-10T16:00:00Z"})
            assert result.status_code == 200
            snap = result.json()
            # The snapshot is saved immediately with the deterministic brief; the Akamai brief follows
            # as a separate, append-only add-on and never edits the snapshot.
            assert snap["model_id"] == "deterministic-fallback"
            assert snap["ai_addon"]["status"] in ("pending", "ok")
            assert snap["posture"]["posture"] == "EARLY_DISMISSAL"
            assert snap["integrity_ok"]
            addon = {"status": "pending"}
            for _ in range(100):
                addon = client.get(f"/api/snapshot/{snap['snapshot_id']}/interpretation").json()
                if addon["status"] != "pending":
                    break
                time.sleep(0.05)
            assert addon["status"] == "ok" and addon["model_id"] == "akamai:hackathon-chat"
            assert addon["ai"]["summary"] and addon["ai"]["evidence_rule_ids"]
            assert addon["ai"]["suggested_reasons"]
            assert addon["ai"]["inference"]["requests"][0]["usage"]["total_tokens"] == 300
            with engine.begin() as c, pytest.raises(DBAPIError, match="append-only"):
                c.execute(text("UPDATE snapshotinterpretation SET status='failed'"))
            assert client.get("/api/decisions").json() == []
            assert client.post("/api/notifications/packages", json={"decision_id": 999}).status_code == 404
            decision = {"snapshot_id": snap["snapshot_id"], "decided_by": "Test Manager", "decision_posture": "TELEWORK"}
            assert client.post("/api/decisions", json=decision).status_code == 422
            decision["override_reason"] = "Test override after reviewing the recorded evidence"
            assert client.post("/api/decisions", json={**decision, "decided_by": "  "}).status_code == 422
            accepted = client.post("/api/decisions", json=decision)
            assert accepted.status_code == 201
            assert not accepted.json()["agreed_with_recommendation"]
            record = client.get("/api/record/" + snap["snapshot_id"]).json()
            assert record["snapshot"]["integrity_ok"]
            assert record["snapshot"]["ai_addon"]["model_id"] == "akamai:hackathon-chat"
            assert record["decisions"][0]["decision_posture"] == "TELEWORK"
            assert record["snapshot"]["posture"]["posture"] == "EARLY_DISMISSAL"
            did = accepted.json()["id"]
            result = client.post("/api/notifications/packages", json={"decision_id": did})
            assert result.status_code == 200
            package = result.json()
            assert package["posture"] == "TELEWORK"  # The manager's override, not the AI recommendation.
            assert package["groups"] and package["messages"] == []
            assert not any(g["approved"] for g in package["groups"])
            assert "Powered by Akamai" in package["draft_source"]
            assert package["draft_inference"]["requests"][0]["usage"]["total_tokens"] == 30
            assert any("telework" in g["instruction"] for g in package["groups"])
            action = {"version": package["version"], "actor": "Test Manager"}
            assert client.post(f"/api/notifications/packages/{package['id']}/send", json=action).status_code == 422
            assert client.post("/api/notifications/packages", json={"decision_id": did}).json()["id"] == package["id"]
            assert len(notification_calls) == 1  # Reopening a draft never repeats inference.
            stored = client.get("/api/notifications").json()["packages"][0]
            assert stored["draft_inference"] == package["draft_inference"]
            audit = client.get(f"/api/notifications/packages/{package['id']}/audit").json()
            assert json.loads(audit[0]["detail_json"])["draft_inference"] == package["draft_inference"]
    finally:
        db.set_engine(old)
        engine.dispose()


def test_regenerate_brief_appends_a_new_addon(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "model_provider", "akamai")
    monkeypatch.setattr(settings, "akamai_api_key", "test-team-key")
    old = db._engine
    engine = db.make_engine(f"sqlite:///{tmp_path / 'regen.db'}")
    db.set_engine(engine)
    calls = []
    async def inference(provider, snap, feedback):
        calls.append(snap["snapshot_id"])
        return fallback.build(snap).model_copy(update={"headline": f"Early dismissal brief {len(calls)}"}), {
            "provider": "akamai", "model": "hackathon-chat", "usage": None}
    monkeypatch.setattr(agent, "_run_agent", inference)

    def wait(client, sid):
        for _ in range(100):
            a = client.get(f"/api/snapshot/{sid}/interpretation").json()
            if a["status"] != "pending":
                return a
            time.sleep(0.05)
        return a
    try:
        with TestClient(app) as client:
            sid = client.post("/api/evaluate", json={"mode": "replay", "as_of": "2020-08-10T16:00:00Z"}).json()["snapshot_id"]
            first = wait(client, sid)
            assert first["status"] == "ok" and first["ai"]["headline"].endswith("1")
            r = client.post(f"/api/snapshot/{sid}/interpretation")
            assert r.status_code == 202 and r.json()["status"] in ("pending", "ok")
            second = wait(client, sid)
            assert second["ai"]["headline"].endswith("2") and len(calls) == 2
            assert client.get(f"/api/snapshot/{sid}").json()["integrity_ok"]
            assert client.post("/api/snapshot/nope/interpretation").status_code == 404
            monkeypatch.setattr(settings, "model_provider", "none")
            assert client.post(f"/api/snapshot/{sid}/interpretation").status_code == 409
    finally:
        db.set_engine(old)
        engine.dispose()


def test_loading_stored_backtest_starts_default_brief(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "model_provider", "akamai")
    monkeypatch.setattr(settings, "akamai_api_key", "test-team-key")
    monkeypatch.setattr(settings, "strands_fallback_enabled", False)
    old = db._engine
    engine = db.make_engine(f"sqlite:///{tmp_path / 'load.db'}")
    db.set_engine(engine)
    calls = []

    async def inference(provider, snap, feedback):
        calls.append((provider, snap["mode"]))
        return fallback.build(snap), {"provider": "akamai", "model": "hackathon-chat", "usage": None}

    monkeypatch.setattr(agent, "_run_agent", inference)
    try:
        stored = asyncio.run(snapshots.evaluate(
            load_facility(), datetime(2020, 8, 10, 16, tzinfo=timezone.utc), "backtest", use_ai=False,
        ))
        assert stored["ai_addon"]["status"] == "none"
        with TestClient(app) as client:
            loaded = client.get(f"/api/snapshot/{stored['snapshot_id']}").json()
            assert loaded["ai_addon"]["status"] in ("pending", "ok")
            for _ in range(100):
                addon = client.get(f"/api/snapshot/{stored['snapshot_id']}/interpretation").json()
                if addon["status"] != "pending":
                    break
                time.sleep(0.05)
            assert addon["status"] == "ok"
            assert addon["model_id"] == "akamai:hackathon-chat"
            assert calls == [("akamai", "backtest")]
            assert client.post(f"/api/snapshot/{stored['snapshot_id']}/interpretation").status_code == 202
    finally:
        db.set_engine(old)
        engine.dispose()
