import httpx
import pytest

from backend.app.api.main import app
from backend.app.config import get_settings


@pytest.mark.asyncio
async def test_full_human_approval_and_simulated_send_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_DIR", str(tmp_path / "evidence"))
    get_settings.cache_clear()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/api/health")
            assert health.status_code == 200
            decision = await client.post(
                "/api/facilities/ia-des-moines/decision",
                json={"action": "approved", "actor": "Morgan Manager"},
            )
            assert decision.status_code == 200, decision.text
            package_id = decision.json()["notification_package"]["id"]
            sent = await client.post(
                f"/api/notifications/{package_id}/send", json={"simulate": True}
            )
            assert sent.status_code == 200
            assert sent.json()["events"]
            verified = await client.get("/api/records/verify")
            assert verified.json()["intact"] is True
    get_settings.cache_clear()
