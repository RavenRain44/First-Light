"""Official DriveNC live camera views. No historical images are substituted.

Only documented provider camera-view URLs are proxied; credentials never go to
the browser. Returned camera images remain human situational context.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

import httpx

from adapters import cache
from adapters.base import Facility
from adapters.iem_cameras import IMAGE_DIR, _bearing, _km, image_path
from adapters.iem_roads import point_to_polyline_km
from adapters.ncdot import CAMERAS_URL, get_feed, number
from app.config import settings

NEAREST = 16
MAX_DISTANCE_KM = 65
VIEW_HOSTS = {"www.drivenc.gov", "drivenc.gov", "nc.traveliq.co", "nc.stage.traveliq.co"}
VIEW_PATH = re.compile(r"^/map/Cctv/\d+/?$", re.I)


def is_snapshot(url: str) -> bool:
    try:
        parsed = urlparse(url or "")
        return (parsed.scheme == "https" and parsed.hostname in VIEW_HOSTS and parsed.port in (None, 443)
                and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                and bool(VIEW_PATH.fullmatch(parsed.path)))
    except ValueError:
        return False


def parse_traffic_cameras(rows: list[dict], facility: Facility, fetched_at: datetime, nearest: int = NEAREST) -> list[dict]:
    out = []
    for row in rows:
        lat, lon = number(row.get("Latitude")), number(row.get("Longitude"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        distance = _km(lat, lon, facility.lat, facility.lon)
        if distance > MAX_DISTANCE_KM:
            continue
        views = []
        for view in row.get("Views") or []:
            url = view.get("Url") or ""
            if view.get("Status") != "Enabled" or not is_snapshot(url):
                continue
            views.append({"view": view.get("Id", len(views)), "url": url,
                          "time": fetched_at.isoformat(), "label": view.get("Description") or "Live view",
                          "timestamp_basis": "Camera list retrieval; individual image capture time is unavailable."})
        if not views:
            continue
        corridor = next((c for c in facility.corridors if point_to_polyline_km((lon, lat), c.coordinates) <= 2), None)
        out.append({"id": f"ncdot-{row.get('Id')}", "kind": "traffic", "provider": "NCDOT",
                    "source": row.get("Source") or "NCDOT DriveNC", "name": row.get("Location") or row.get("Roadway") or "DriveNC camera",
                    "lat": lat, "lon": lon, "km": round(distance, 1),
                    "direction": _bearing(lat, lon, facility.lat, facility.lon),
                    "corridor": corridor.id if corridor else None, "corridor_name": corridor.name if corridor else None,
                    "updated": fetched_at.isoformat(), "snapshot_url": views[0]["url"], "views": views,
                    "timestamp_basis": "List retrieval time; individual image capture time is not supplied by the feed."})
    return sorted(out, key=lambda c: c["km"])[:nearest]


async def fetch_traffic_cameras(facility: Facility, nearest: int = NEAREST, *, allow_demo_bypass: bool = False):
    if facility.state != "NC":
        raise cache.SourceUnavailable("DriveNC camera feed covers North Carolina only.")
    response = await get_feed(CAMERAS_URL, ttl=300, allow_demo_bypass=allow_demo_bypass)
    return parse_traffic_cameras(response.data, facility, response.fetched_at, nearest), response


async def get_image(url: str, allow_stale: bool = True) -> bytes | None:
    if not is_snapshot(url):
        raise ValueError("Only documented DriveNC camera-view URLs are served.")
    path = image_path(url)
    if settings.demo_mode:
        return path.read_bytes() if path.exists() else None
    try:
        # Redirects are not followed into unverified hosts or routes.
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": settings.nws_user_agent}) as client:
            response = await client.get(url)
        if response.status_code == 200 and response.headers.get("content-type", "").startswith("image/") and len(response.content) <= 8*1024*1024:
            IMAGE_DIR.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(response.content)
            temporary.replace(path)
            return response.content
    except httpx.HTTPError:
        pass
    return path.read_bytes() if allow_stale and path.exists() else None
