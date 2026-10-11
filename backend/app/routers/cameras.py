"""Iowa DOT camera locations and images (situational awareness; not used in the recommendation)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from adapters.base import utc
from adapters.cache import SourceUnavailable, cached_fetched_at
from adapters.iem_cameras import cameras_url, fetch_cameras, get_image, is_cached, load_demo_list
from app import snapshots
from app.config import settings
from app.facility import get_facility

router = APIRouter(prefix="/api/cameras")


async def _live_time(facility) -> datetime:
    if not settings.demo_mode:
        return datetime.now(timezone.utc)
    # Demo "live" = when the cached live camera list was fetched (scripts/cache_cameras.py),
    # so the list and its cached images always come from the same moment.
    cached = cached_fetched_at(cameras_url(datetime.now(timezone.utc), live=True))
    return cached or settings.demo_reference_now or await snapshots.demo_live_as_of(facility) or datetime.now(timezone.utc)


@router.get("")
async def cameras(as_of: datetime | None = None, facility_id: str | None = None):
    f = get_facility(facility_id)
    live = as_of is None
    pinned = load_demo_list() if (live and settings.demo_mode) else None
    if pinned:
        cams, t = pinned
        source_url, fetched = cameras_url(t, live=True), t
    else:
        t = await _live_time(f) if live else utc(as_of)
        try:
            cams, r = await fetch_cameras(f, t, live=True if live else None)
        except SourceUnavailable:
            msg = ("Camera images for this time aren't in the offline cache." if settings.demo_mode
                   else "Iowa DOT camera list is unavailable right now.")
            return {"status": "unavailable", "detail": msg, "cameras": [], "as_of": t.isoformat()}
        source_url, fetched = r.url, r.fetched_at
    if settings.demo_mode:
        # Offline: only offer images that were cached ahead of time; hide cameras left with none.
        for c in cams:
            c["views"] = [v for v in c["views"] if is_cached(v["url"])]
        cams = [c for c in cams if c["views"]]
    return {
        "status": "ok" if cams else "empty",
        "detail": None if cams else "No Iowa DOT camera images available for this time.",
        "as_of": t.isoformat(), "source": "Iowa DOT RWIS cameras via IEM", "source_url": source_url,
        "fetched_at": fetched.isoformat(), "cameras": cams,
        "note": "Still images, refreshed every few minutes. For situational awareness; not used in the recommendation.",
    }


@router.get("/image")
async def image(u: str = Query(..., description="IEM camera image URL")):
    try:
        data = await get_image(u)
    except ValueError:
        raise HTTPException(400, "only Iowa Environmental Mesonet camera images are served")
    if data is None:
        raise HTTPException(404, "image unavailable")
    # Archived frames never change, so browsers may keep them.
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/decision/{decision_id}")
def decision_cameras(decision_id: int):
    from app.camera_archive import saved
    return saved(decision_id)


@router.get("/saved-frame/{frame_id}")
def saved_frame(frame_id: str):
    from app.db import session
    from app.models import DecisionCameraFrame
    with session() as s:
        row = s.get(DecisionCameraFrame, frame_id)
        if not row:
            raise HTTPException(404, "Saved camera frame unavailable")
        return Response(content=row.image, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})
