"""Akamai Object Storage status and signed links to a snapshot's stored log, chart data and camera stills."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from app import snapshots, storage

router = APIRouter(prefix="/api/storage")


@router.get("/status")
def status():
    return storage.status()


@router.post("/sync")
async def sync_now():
    if not storage.enabled():
        raise HTTPException(409, "Object storage is not configured")
    written = await storage.sync_once()
    return {**storage.status(), "written": written}


@router.get("/record/{snapshot_id}")
async def record(snapshot_id: str):
    if not snapshots.get(snapshot_id):
        raise HTTPException(404, "snapshot not found")
    try:
        return await asyncio.to_thread(storage.record_links, snapshot_id)
    except Exception as e:  # noqa: BLE001 - the bucket being down must not break the dashboard
        return {"enabled": True, "error": f"Object storage unavailable: {type(e).__name__}"}
