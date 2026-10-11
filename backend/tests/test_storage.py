"""Object storage mirror: append-only sync, chart data, decision camera stills, backups and signed links."""
import asyncio
import json

from fastapi.testclient import TestClient

from app import db, storage
from app.config import settings
from app.main import app


class FakeBucket:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.fail = False

    def put(self, key, data, content_type):
        if self.fail:
            raise ConnectionError("bucket unreachable")
        self.objects[key] = data

    def get(self, key):
        return self.objects.get(key)

    def list(self, prefix):
        return sorted(k for k in self.objects if k.startswith(prefix))

    def link(self, key, seconds):
        return f"https://bucket.example/{key}?expires={seconds}"


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "model_provider", "none")
    monkeypatch.setattr(settings, "db_path", tmp_path / "s.db")
    old = db._engine
    db.set_engine(db.make_engine(f"sqlite:///{tmp_path / 's.db'}"))
    bucket = FakeBucket()
    storage.set_bucket(bucket)
    return bucket, old


def test_sync_mirrors_records_graphs_and_decision_cameras(tmp_path, monkeypatch):
    bucket, old = _setup(tmp_path, monkeypatch)
    images = []

    async def fake_cameras(as_of=None, facility_id=None):
        return {"cameras": [{"id": f"C{i}", "name": f"Cam {i}", "km": i, "direction": "N",
                             "views": [{"view": 0, "label": "North", "url": f"https://img/{i}", "time": "2020-08-10T15:55:00+00:00"}]}
                            for i in range(12)]}

    async def fake_image(url):
        images.append(url)
        return b"\xff\xd8jpeg" if not url.endswith("/3") else None  # one camera has no image: skipped

    monkeypatch.setattr("app.routers.cameras.cameras", fake_cameras)
    monkeypatch.setattr("adapters.iem_cameras.get_image", fake_image)
    try:
        with TestClient(app) as client:
            snap = client.post("/api/evaluate", json={"mode": "replay", "as_of": "2020-08-10T16:00:00Z"}).json()
            sid = snap["snapshot_id"]
            r = client.post("/api/decisions", json={"snapshot_id": sid, "decided_by": "Test Manager",
                                                    "decision_posture": snap["posture"]["posture"]})
            assert r.status_code == 201
            did = r.json()["id"]
            client.post("/api/storage/sync")

            keys = bucket.objects
            day = snap["created_at"][:10]
            assert json.loads(keys[f"logs/snapshots/{day}/{sid}.json"])["snapshot_id"] == sid
            graph = json.loads(keys[f"graphs/{sid}.json"])
            assert graph["rows"] and graph["threshold_lines"]
            decision = json.loads(next(v for k, v in keys.items() if k.startswith("logs/decisions/")))
            assert decision["id"] == did and decision["decided_by"] == "Test Manager"
            index = json.loads(keys[f"cameras/{sid}/decision-{did}/index.json"])
            assert len(index["images"]) == storage.CAMERAS_PER_DECISION
            assert "https://img/3" not in [i["source_url"] for i in index["images"]]
            assert all(keys[i["key"]].startswith(b"\xff\xd8") for i in index["images"])

            # Append-only: a second pass uploads nothing new.
            before = dict(keys)
            assert client.post("/api/storage/sync").json()["written"] == 0
            assert keys == before

            links = client.get(f"/api/storage/record/{sid}").json()
            assert links["log_url"].startswith("https://bucket.example/logs/snapshots/")
            assert links["graph_url"].endswith(f"graphs/{sid}.json?expires=3600")
            assert len(links["camera_sets"][0]["images"]) == storage.CAMERAS_PER_DECISION
            assert client.get("/api/storage/status").json()["enabled"]
    finally:
        storage.set_bucket(None)
        db.set_engine(old)


def test_outage_is_retried_from_the_marker(tmp_path, monkeypatch):
    bucket, old = _setup(tmp_path, monkeypatch)
    try:
        with TestClient(app) as client:
            bucket.fail = True
            sid = client.post("/api/evaluate", json={"mode": "replay", "as_of": "2020-08-10T16:00:00Z"}).json()["snapshot_id"]
            client.post("/api/storage/sync")
            status = client.get("/api/storage/status").json()
            assert "unreachable" in status["last_error"] and not bucket.objects
            bucket.fail = False
            client.post("/api/storage/sync")
            assert f"graphs/{sid}.json" in bucket.objects
            assert client.get("/api/storage/status").json()["last_error"] is None
    finally:
        storage.set_bucket(None)
        db.set_engine(old)


def test_backup_and_restore_on_a_fresh_server(tmp_path, monkeypatch):
    bucket, old = _setup(tmp_path, monkeypatch)
    try:
        with TestClient(app) as client:
            client.post("/api/evaluate", json={"mode": "replay", "as_of": "2020-08-10T16:00:00Z"})
        asyncio.run(storage.backup())
        assert bucket.objects["backups/closurecall-latest.db"].startswith(b"SQLite format 3")
        fresh = tmp_path / "fresh" / "closurecall.db"
        monkeypatch.setattr(settings, "db_path", fresh)
        assert storage.restore_if_empty() and fresh.read_bytes() == bucket.objects["backups/closurecall-latest.db"]
        assert not storage.restore_if_empty()  # never overwrites an existing database
    finally:
        storage.set_bucket(None)
        db.set_engine(old)


def test_storage_off_without_settings():
    storage.set_bucket(None)
    assert storage.status()["enabled"] is False
    assert storage.record_links("x") == {"enabled": False}
    assert asyncio.run(storage.sync_once()) == 0
