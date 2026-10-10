"""API-level verification of an Akamai brief and the manager's separate decision."""
from fastapi.testclient import TestClient

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
    try:
        with TestClient(app) as client:
            result = client.post("/api/evaluate", json={"mode": "replay", "as_of": "2020-08-10T16:00:00Z"})
            assert result.status_code == 200
            snap = result.json()
            assert snap["model_id"] == "akamai:hackathon-chat"
            assert snap["posture"]["posture"] == "EARLY_DISMISSAL"
            assert snap["ai"]["summary"] and snap["ai"]["evidence_rule_ids"]
            assert snap["ai"]["inference"]["requests"][0]["usage"]["total_tokens"] == 300
            assert snap["integrity_ok"]
            assert client.get("/api/decisions").json() == []
            decision = {"snapshot_id": snap["snapshot_id"], "decided_by": "Test Manager", "decision_posture": "TELEWORK"}
            assert client.post("/api/decisions", json=decision).status_code == 422
            decision["override_reason"] = "Test override after reviewing the recorded evidence"
            accepted = client.post("/api/decisions", json=decision)
            assert accepted.status_code == 201
            assert not accepted.json()["agreed_with_recommendation"]
            record = client.get("/api/record/" + snap["snapshot_id"]).json()
            assert record["snapshot"]["integrity_ok"]
            assert record["snapshot"]["model_id"] == "akamai:hackathon-chat"
            assert record["decisions"][0]["decision_posture"] == "TELEWORK"
            assert record["snapshot"]["posture"]["posture"] == "EARLY_DISMISSAL"
    finally:
        db.set_engine(old)
        engine.dispose()
