"""Iowa DOT camera locations and images (situational awareness; not used in the recommendation).

Two networks: RWIS weather-station cameras (stills, archived, so they follow Replay) and the
511 traffic cameras around Ames (live HLS video, live view only).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from adapters.base import utc
from adapters.cache import SourceUnavailable, cached_fetched_at
from adapters.iem_cameras import cameras_url, fetch_cameras, fetch_webcams, get_image, is_cached, is_snapshot, load_demo_list
from adapters.iowadot_cameras import fetch_traffic_cameras, merge_live
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
            source_url, fetched = r.url, r.fetched_at
        except SourceUnavailable:
            cams, source_url, fetched = [], None, None
        # ISU campus / KCCI webcams are archived too, so they follow Replay like RWIS.
        webcams = await fetch_webcams(f, t, live=True if live else None)
        traffic = []
        if live and not settings.demo_mode:
            try:
                traffic, tr = await fetch_traffic_cameras(f)
            except SourceUnavailable:
                pass  # each network works without the others
            if fetched is None and traffic:
                source_url, fetched = tr.url, tr.fetched_at
        cams = merge_live(cams, traffic, webcams)
        if fetched is None and webcams:
            fetched = t
        if fetched is None:
            msg = ("Camera images for this time aren't in the offline cache." if settings.demo_mode
                   else "Iowa DOT camera list is unavailable right now.")
            return {"status": "unavailable", "detail": msg, "cameras": [], "as_of": t.isoformat()}
    if settings.demo_mode:
        # Offline: only offer images that were cached ahead of time; hide cameras left with none.
        for c in cams:
            c["views"] = [v for v in c["views"] if is_cached(v["url"])]
        cams = [c for c in cams if c["views"]]
    return {
        "status": "ok" if cams else "empty",
        "detail": None if cams else "No camera images available for this time.",
        "as_of": t.isoformat(), "source": ("Iowa DOT traffic cameras (511); Iowa DOT RWIS and ISU/KCCI webcams via IEM" if live
                                         else "Iowa DOT RWIS and ISU/KCCI webcams via IEM"), "source_url": source_url,
        "fetched_at": fetched.isoformat(), "cameras": cams,
        "note": ("Traffic cameras stream live video (live view only); RWIS and ISU/KCCI webcams are stills refreshed every few minutes. "
                 "For situational awareness; not used in the recommendation."),
    }


@router.get("/image")
async def image(u: str = Query(..., description="IEM camera image URL")):
    try:
        data = await get_image(u)
    except ValueError:
        raise HTTPException(400, "only IEM camera archive images and Iowa DOT camera snapshots are served")
    if data is None:
        raise HTTPException(404, "image unavailable")
    # Archived frames never change, so browsers may keep them; traffic snapshots are overwritten every few minutes.
    max_age = 30 if is_snapshot(u) else 86400
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": f"public, max-age={max_age}"})
