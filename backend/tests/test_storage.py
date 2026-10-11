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

    def delete(self, key):
        self.objects.pop(key, None)


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
    async def fake_capture(decision_id, facility_id, as_of, replay=False):
        """Stands in for app.camera_archive.capture: 3 saved angle frames, one camera unavailable."""
        from app.db import session
        from app.models import DecisionCameraArchive, DecisionCameraFrame
        with session() as s:
            row = s.get(DecisionCameraArchive, decision_id)
            cams = [{"id": f"C{i}", "name": f"Cam {i}", "km": i, "direction": "N",
                     "views": [{"view": 0, "label": "North", "url": f"/api/cameras/saved-frame/f{i}",
                                "source_url": f"https://img/{i}", "time": "2020-08-10T15:55:00+00:00"}]} for i in range(3)]
            row.manifest_json = json.dumps({"status": "ok", "cameras": cams, "captured_at": "2020-08-10T16:00:05+00:00",
                                            "unavailable": [{"id": "C9", "name": "Cam 9", "reason": "offline"}]})
            s.add_all([DecisionCameraFrame(id=f"f{i}", decision_id=decision_id, image=b"\xff\xd8jpeg") for i in range(3)])
            s.add(row)
            s.commit()

    monkeypatch.setattr("app.camera_archive.capture", fake_capture)
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
            assert index["status"] == "ok" and len(index["images"]) == 3 and index["unavailable"][0]["id"] == "C9"
            assert all(keys[i["key"]].startswith(b"\xff\xd8") for i in index["images"])

            # Append-only: a second pass uploads nothing new.
            before = dict(keys)
            assert client.post("/api/storage/sync").json()["written"] == 0
            assert keys == before

            links = client.get(f"/api/storage/record/{sid}").json()
            assert links["log_url"].startswith("https://bucket.example/logs/snapshots/")
            assert links["graph_url"].endswith(f"graphs/{sid}.json?expires=3600")
            assert len(links["camera_sets"][0]["images"]) == 3
            assert client.get("/api/storage/status").json()["enabled"]
    finally:
        storage.set_bucket(None)
        db.set_engine(old)


def test_sync_waits_for_a_running_camera_capture(tmp_path, monkeypatch):
    bucket, old = _setup(tmp_path, monkeypatch)

    async def no_capture(*args, **kwargs):
        return None  # capture still "running": the archive stays pending

    monkeypatch.setattr("app.camera_archive.capture", no_capture)
    try:
        with TestClient(app) as client:
            snap = client.post("/api/evaluate", json={"mode": "replay", "as_of": "2020-08-10T16:00:00Z"}).json()
            did = client.post("/api/decisions", json={"snapshot_id": snap["snapshot_id"], "decided_by": "Test Manager",
                                                      "decision_posture": snap["posture"]["posture"]}).json()["id"]
            client.post("/api/storage/sync")
            assert not any(k.startswith("logs/decisions/") for k in bucket.objects)
            assert json.loads(bucket.objects[storage.SYNC_KEY]).get("decision", 0) == 0
            monkeypatch.setattr(storage, "PENDING_GRACE_SECONDS", 0)  # capture abandoned: copy what exists
            client.post("/api/storage/sync")
            assert any(k.endswith(f"/{did}.json") for k in bucket.objects if k.startswith("logs/decisions/"))
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


def test_fresh_machine_loads_the_frozen_dataset_from_the_bucket(tmp_path, monkeypatch):
    """The repository release, uploaded byte for byte, restores the full 7,470-day cohort on an empty machine."""
    from app import dataset_cloud
    from app.config import REPO_DIR
    from app.risk_experiment import manifest_path
    from scripts.dataset_repo import RepositoryBucket, upload

    bucket, old = _setup(tmp_path, monkeypatch)
    repo = RepositoryBucket(REPO_DIR / "backend/data/backtesting")
    try:
        v = "ames-7470-v1"
        assert dataset_cloud.ensure_local(v) is None  # nothing published yet: no error, nothing loaded
        assert dataset_cloud.ensure_local() is None  # the configured forecast dataset isn't in this bucket either
        assert upload(repo)["datasets"] == [v]
        assert bucket.objects == {k: repo.get(k) for k in repo.list("datasets/")}
        result = dataset_cloud.ensure_local(v)
        assert result["evaluations"] == result["cohort_n"] == 7470 and manifest_path().exists()
        assert dataset_cloud.ensure_local(v) is None  # already present: not reloaded
        import sqlite3
        with sqlite3.connect(tmp_path / "s.db") as c:
            assert c.execute("select count(*) from historicalevaluation").fetchone()[0] == 7470
    finally:
        storage.set_bucket(None)
        db.set_engine(old)


def test_forecast_dataset_publish_and_fresh_machine_restore(tmp_path, monkeypatch):
    """Only same-day 04:00 forecast-enabled (archive) evaluations under the current rules form the forecast cohort;
    it publishes to the bucket and a fresh machine loads it as the configured dataset."""
    import gzip
    from app import dataset_cloud, historical
    from app.models import HistoricalArtifact, HistoricalEvaluation

    bucket, old = _setup(tmp_path, monkeypatch)
    try:
        def add(day, mode, decision_day=None):
            as_of = historical.local_instant(day, "04:00")
            id_, rules, config = historical.identity(as_of, mode)
            payload = gzip.compress(json.dumps({"snapshot_id": id_, "day": day}).encode())
            sha = dataset_cloud.sha(payload)
            summary = {"id": id_, "day": day, "as_of": as_of.isoformat(), "requested_mode": mode, "recommendation": "NORMAL",
                       "decision_day": decision_day or day, "outcome": {"gradable": True, "disruptive": False}}
            with db.session() as s:
                s.add(HistoricalArtifact(sha256=sha, payload=payload))
                s.add(HistoricalEvaluation(id=id_, day=day, as_of=as_of.isoformat(), rules_sha=rules.sha256, config_sha=config,
                                           reconstruction="archived forecast reconstruction", status="partial",
                                           summary_json=json.dumps(summary), artifact_sha=sha))
                s.commit()
        add("2024-01-16", "archive")
        add("2024-01-17", "archive")
        add("2024-01-18", "observation")                   # not forecast-enabled
        add("2024-01-19", "archive", decision_day="2024-01-22")  # targets another day
        add("2018-06-01", "archive")                      # before archived forecasts
        m = dataset_cloud.forecast_cohort()
        assert [e["day"] for e in m["entries"]] == ["2024-01-16", "2024-01-17"] and m["version"] == settings.dataset_version
        out = dataset_cloud.publish(manifest=m, sources_from=dataset_cloud.FORECAST_SOURCES_FROM, extras=False)
        assert out["n"] == 2 and any(k.endswith("ames-forecast-v1/latest.json") for k in bucket.objects)

        # Retiring an older version removes only what the configured dataset doesn't use, and only when asked.
        older = {**m, "version": "old-v0"}  # same evaluations: its year bundle is shared with the new release
        dataset_cloud.publish(manifest=older, extras=False)
        before = dict(bucket.objects)
        plan = dataset_cloud.retire("old-v0")
        assert plan["dry_run"] and bucket.objects == before and plan["shared_objects_kept"] >= 1
        assert all(k.startswith("datasets/old-v0/") or k.startswith("datasets/objects/") for k in plan["keys"])
        dataset_cloud.retire("old-v0", dry_run=False)
        assert not any(k.startswith("datasets/old-v0/") for k in bucket.objects)
        assert dataset_cloud.catalog("ames-forecast-v1")["n"] == 2  # still complete and verified
        for item in dataset_cloud.catalog("ames-forecast-v1")["items"].values():
            assert item["key"] in bucket.objects

        fresh = tmp_path / "fresh"
        fresh.mkdir()
        monkeypatch.setattr(settings, "db_path", fresh / "s.db")
        db.set_engine(db.make_engine(f"sqlite:///{fresh / 's.db'}"))
        result = dataset_cloud.ensure_local()
        assert result["evaluations"] == result["cohort_n"] == 2 and dataset_cloud.cohort_path("ames-forecast-v1").exists()
        assert dataset_cloud.ensure_local() is None
    finally:
        storage.set_bucket(None)
        db.set_engine(old)
