"""Akamai Object Storage (S3-compatible) mirror of the decision record, chart data and decision camera stills.

The SQLite database stays the source of truth. Its record tables are append-only, so a background sync
copies each new row to the bucket once, in order, tracking the last copied row id per table in
``logs/_sync.json``. Writes never wait on the bucket: if it is slow or unreachable the app keeps working
and the next pass catches up. With no ``OBJ_*`` settings, storage is off and nothing changes.

Bucket layout (private; the app hands out short-lived signed links):

    logs/snapshots/YYYY-MM-DD/<snapshot_id>.json        full snapshot (evidence, rules, posture, brief)
    logs/briefs/YYYY-MM-DD/<id>.json                    Akamai brief add-ons
    logs/decisions/YYYY-MM-DD/<id>.json                 manager decisions
    logs/notifications/YYYY-MM-DD/<id>.json             notification audit trail
    graphs/<snapshot_id>.json                           chart data, redrawn identically on any device
    cameras/<snapshot_id>/decision-<id>/index.json      camera frames saved when a decision is recorded
    backups/closurecall-latest.db, closurecall-YYYY-MM-DD.db   SQLite backups
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import text

from app.config import settings

log = logging.getLogger("closurecall.storage")

SYNC_KEY = "logs/_sync.json"
LINK_SECONDS = 3600
# (table, id column, key prefix, date column). rowid orders inserts even where the primary key is text.
TABLES = [
    ("snapshot", "snapshot_id", "logs/snapshots", "created_at"),
    ("snapshotinterpretation", "id", "logs/briefs", "created_at"),
    ("decision", "id", "logs/decisions", "decided_at"),
    ("notificationaudit", "id", "logs/notifications", "at"),
]


class Bucket(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes | None: ...
    def list(self, prefix: str) -> list[str]: ...
    def link(self, key: str, seconds: int) -> str: ...


class S3Bucket:
    """Akamai Object Storage through boto3 (the service speaks the S3 API)."""

    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str, region: str, prefix: str = ""):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""  # e.g. "dev/" keeps local runs apart
        self.client = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=access_key,
                                   aws_secret_access_key=secret_key, region_name=region,
                                   config=Config(signature_version="s3v4", retries={"max_attempts": 3},
                                                 connect_timeout=5, read_timeout=20))

    def put(self, key, data, content_type):
        self.client.put_object(Bucket=self.bucket, Key=self.prefix + key, Body=data, ContentType=content_type, ACL="private")

    def get(self, key):
        try:
            return self.client.get_object(Bucket=self.bucket, Key=self.prefix + key)["Body"].read()
        except self.client.exceptions.NoSuchKey:
            return None

    def list(self, prefix):
        keys = []
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=self.prefix + prefix):
            keys += [o["Key"][len(self.prefix):] for o in page.get("Contents", [])]
        return keys

    def link(self, key, seconds):
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": self.prefix + key}, ExpiresIn=seconds)

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=self.prefix + key)


_bucket: Bucket | None = None
_state: dict[str, Any] = {"last_sync": None, "last_error": None, "uploaded": 0, "backup": None}
_wake: asyncio.Event | None = None
_loop: asyncio.AbstractEventLoop | None = None
_lock: asyncio.Lock | None = None


def configure() -> Bucket | None:
    """Connect to the bucket named in the environment (or leave storage off)."""
    global _bucket
    if _bucket is None and settings.obj_bucket and settings.obj_access_key and settings.obj_secret_key:
        _bucket = S3Bucket(settings.obj_endpoint, settings.obj_bucket, settings.obj_access_key,
                           settings.obj_secret_key, settings.obj_region, settings.obj_prefix)
    _listen_for_commits()
    return _bucket


_listening = False


def _listen_for_commits() -> None:
    """Every committed record write wakes the sync loop, so new rows reach the bucket within seconds."""
    global _listening
    if not _listening:
        from sqlalchemy import event
        from sqlmodel import Session
        event.listen(Session, "after_commit", lambda _s: kick())
        _listening = True


def set_bucket(bucket: Bucket | None) -> None:
    """Tests swap in an in-memory bucket."""
    global _bucket
    _bucket = bucket
    _state.update(last_sync=None, last_error=None, uploaded=0, backup=None)


def enabled() -> bool:
    return _bucket is not None


def status() -> dict:
    return {"enabled": enabled(), "provider": "Akamai Object Storage" if enabled() else None,
            "bucket": (settings.obj_bucket + ("/" + settings.obj_prefix.strip("/") if settings.obj_prefix.strip("/") else "")) if enabled() else None,
            "endpoint": settings.obj_endpoint if enabled() else None, **_state}


def kick() -> None:
    """Ask the background loop to sync soon (called after a record is written)."""
    if _wake is not None and _loop is not None and not _loop.is_closed() and enabled():
        try:
            _loop.call_soon_threadsafe(_wake.set)  # commits can happen on worker threads
        except RuntimeError:
            pass  # the loop shut down between the check and the call


def _json(x: Any) -> bytes:
    return json.dumps(x, indent=2, default=str).encode()


def _day(v: Any) -> str:
    return str(v)[:10] if v else "undated"


# ----------------------------------------------------------------------------- sync

def _marker() -> dict[str, int]:
    raw = _bucket.get(SYNC_KEY)
    return json.loads(raw) if raw else {}


def _new_rows(table: str, after: int) -> list[dict]:
    from app.db import get_engine
    with get_engine().connect() as c:
        rows = c.execute(text(f"SELECT rowid AS _rowid, * FROM {table} WHERE rowid > :a ORDER BY rowid LIMIT 200"), {"a": after})
        return [dict(r._mapping) for r in rows]


def _snapshot_files(row: dict) -> list[tuple[str, bytes]]:
    from app import snapshots
    from app.routers.core import build_timeseries
    snap = snapshots.get(row["snapshot_id"])
    if not snap:
        return []
    files = [(f"logs/snapshots/{_day(row['created_at'])}/{row['snapshot_id']}.json", _json(snap))]
    if snap.get("mode") != "backtest":  # backtests are rebuilt from fixtures; their charts aren't needed
        files.append((f"graphs/{row['snapshot_id']}.json", _json(build_timeseries(snap))))
    return files


PENDING_GRACE_SECONDS = 600


def _decision_cameras(row: dict) -> list[tuple[str, bytes, str]] | None:
    """The camera frames saved when the decision was recorded (app.camera_archive), copied to the bucket.

    Returns None while the capture is still running, so the sync waits and copies the finished set.
    """
    from app.db import session
    from app.models import DecisionCameraArchive, DecisionCameraFrame
    from sqlmodel import select
    with session() as s:
        archive = s.get(DecisionCameraArchive, row["id"])
        decided = datetime.fromisoformat(str(row["decided_at"])).replace(tzinfo=timezone.utc)
        recent = (datetime.now(timezone.utc) - decided).total_seconds() < PENDING_GRACE_SECONDS
        if archive is None:
            # Just recorded: the capture row is written right after the decision. Older decisions predate capture.
            return None if recent else []
        manifest = json.loads(archive.manifest_json)
        if manifest.get("status") == "pending" and recent:
            return None
        frames = {f.id: f.image for f in s.exec(select(DecisionCameraFrame).where(DecisionCameraFrame.decision_id == row["id"])).all()}
    base = f"cameras/{row['snapshot_id']}/decision-{row['id']}"
    files, images = [], []
    for cam in manifest.get("cameras", []):
        for v in cam.get("views", []):
            frame_id = str(v.get("url", "")).rsplit("/", 1)[-1]
            if frame_id not in frames:
                continue
            key = f"{base}/{cam['id']}-{v.get('view', 0)}.jpg"
            files.append((key, frames[frame_id], "image/jpeg"))
            images.append({"key": key, "camera": cam.get("name"), "view": v.get("label"), "time": v.get("time"),
                           "km": cam.get("km"), "direction": cam.get("direction"), "source_url": v.get("source_url")})
    files.append((f"{base}/index.json", _json({"snapshot_id": row["snapshot_id"], "decision_id": row["id"],
                                                "captured_at": manifest.get("captured_at"), "status": manifest.get("status"),
                                                "detail": manifest.get("detail"), "images": images,
                                                "unavailable": manifest.get("unavailable", [])}), "application/json"))
    return files


async def sync_once() -> int:
    """Copy every record row added since the last pass. Returns the number of objects written."""
    if not enabled():
        return 0
    global _lock
    loop = asyncio.get_running_loop()
    if _lock is None or _lock[0] is not loop:
        _lock = (loop, asyncio.Lock())  # one pass at a time per event loop
    async with _lock[1]:
        written = 0
        try:
            marker = await asyncio.to_thread(_marker)
            for table, idcol, prefix, datecol in TABLES:
                waiting = False
                while not waiting and (rows := await asyncio.to_thread(_new_rows, table, marker.get(table, 0))):
                    for row in rows:
                        if table == "snapshot":
                            files = [(k, b, "application/json") for k, b in await asyncio.to_thread(_snapshot_files, row)]
                        else:
                            body = {k: v for k, v in row.items() if k != "_rowid"}
                            files = [(f"{prefix}/{_day(row[datecol])}/{row[idcol]}.json", _json(body), "application/json")]
                            if table == "decision":
                                cams = await asyncio.to_thread(_decision_cameras, row)
                                if cams is None:
                                    waiting = True  # camera capture still running; copy this decision on a later pass
                                    break
                                files += cams
                        for key, data, ctype in files:
                            await asyncio.to_thread(_bucket.put, key, data, ctype)
                            written += 1
                        marker[table] = row["_rowid"]
                        # Save progress after each row so a crash never re-uploads or skips one.
                        await asyncio.to_thread(_bucket.put, SYNC_KEY, _json(marker), "application/json")
            _state.update(last_sync=datetime.now(timezone.utc).isoformat(), last_error=None)
        except Exception as e:  # noqa: BLE001 - keep serving; the next pass retries from the marker
            _state["last_error"] = f"{type(e).__name__}: {e}"
            log.warning("object storage sync failed: %s", e)
        _state["uploaded"] += written
        return written


# ----------------------------------------------------------------------------- database backup

def _backup_bytes() -> bytes:
    """A consistent copy of the live SQLite file (the backup API works while the app is writing)."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "backup.db"
        src, dst = sqlite3.connect(settings.db_path), sqlite3.connect(out)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return out.read_bytes()


async def backup() -> str | None:
    if not enabled() or not settings.db_path.exists():
        return None
    try:
        data = await asyncio.to_thread(_backup_bytes)
        day = datetime.now(timezone.utc).date().isoformat()
        for key in (f"backups/closurecall-{day}.db", "backups/closurecall-latest.db"):
            await asyncio.to_thread(_bucket.put, key, data, "application/vnd.sqlite3")
        _state["backup"] = datetime.now(timezone.utc).isoformat()
        return day
    except Exception as e:  # noqa: BLE001
        _state["last_error"] = f"backup: {type(e).__name__}: {e}"
        log.warning("database backup failed: %s", e)
        return None


def restore_if_empty() -> bool:
    """On a fresh server (no database yet), start from the latest bucket backup so history carries over."""
    if not enabled() or settings.db_path.exists():
        return False
    try:
        data = _bucket.get("backups/closurecall-latest.db")
    except Exception as e:  # noqa: BLE001
        log.warning("could not read backup from object storage: %s", e)
        return False
    if not data:
        return False
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.db_path.write_bytes(data)
    log.info("restored database from object storage backup (%d bytes)", len(data))
    return True


async def run_loop(backup_hours: float = 24) -> None:
    """Background worker: sync when woken (or every minute), back up the database daily."""
    global _wake, _loop
    _wake, _loop = asyncio.Event(), asyncio.get_running_loop()
    last_backup = datetime.now(timezone.utc)
    try:
        await sync_once()
        while True:
            try:
                await asyncio.wait_for(_wake.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass
            _wake.clear()
            await sync_once()
            if (datetime.now(timezone.utc) - last_backup).total_seconds() >= backup_hours * 3600:
                await backup()
                last_backup = datetime.now(timezone.utc)
    finally:
        _wake = _loop = None


# ----------------------------------------------------------------------------- links for the dashboard

def record_links(snapshot_id: str) -> dict:
    """Signed links to everything stored for one snapshot: its log, chart data, decisions and camera stills."""
    if not enabled():
        return {"enabled": False}
    keys = _bucket.list("logs/snapshots/")
    log_key = next((k for k in keys if k.endswith(f"/{snapshot_id}.json")), None)
    graph = f"graphs/{snapshot_id}.json"
    has_graph = bool(_bucket.list(graph))
    decisions = []
    for idx in sorted(k for k in _bucket.list(f"cameras/{snapshot_id}/") if k.endswith("/index.json")):
        meta = json.loads(_bucket.get(idx) or b"{}")
        decisions.append({"decision_id": meta.get("decision_id"), "captured_at": meta.get("captured_at"),
                          "images": [{**i, "url": _bucket.link(i["key"], LINK_SECONDS)} for i in meta.get("images", [])]})
    return {"enabled": True, "expires_in": LINK_SECONDS,
            "log_url": _bucket.link(log_key, LINK_SECONDS) if log_key else None,
            "graph_url": _bucket.link(graph, LINK_SECONDS) if has_graph else None,
            "camera_sets": decisions}
