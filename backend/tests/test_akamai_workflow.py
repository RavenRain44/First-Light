"""API verification of Akamai briefs, manager decisions and approval-only notifications."""
import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ai import agent, fallback
from app import db
from app.config import settings
from app.main import app


def test_brief_does_not_decide_and_manager_override_is_audited(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "model_provider", "akamai")
    monkeypatch.setattr(settings, "akamai_api_key", "test-team-key")
    monkeypatch.setattr(settings, "aws_fallback_enabled", False)
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
