"""Iowa DOT roadside (RWIS) cameras via the IEM archive: locations and still images.

For human situational awareness only: cameras are NOT inputs to the recommendation
and are not stored on snapshots. Images are stills refreshed every few minutes,
not video. Replay uses the archive at the same 3-hour grid as road conditions, and
never shows an image taken after ``as_of``.

Images are fetched through a small local cache (backend/var/camera_cache) so the
offline demo can show them; in DEMO_MODE only cached images are offered.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from adapters import cache
from adapters.base import Facility, is_historical, iso_z, utc
from adapters.iem_roads import archive_time, point_to_polyline_km
from app.config import settings

IEM = "https://mesonet.agron.iastate.edu/api/1"
NEAREST = 20
LIVE_MAX_AGE = timedelta(hours=3)  # a live camera whose newest image is older than this is treated as offline
CORRIDOR_KM = 2.0
IMAGE_URL = re.compile(r"^https://mesonet\.agron\.iastate\.edu/archive/data/\d{4}/\d{2}/\d{2}/camera/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+_(\d{12})\.jpg$")
IMAGE_DIR = settings.db_path.parent / "camera_cache"
DEMO_LIST = "live_list.json"  # pinned live camera list written by scripts/cache_cameras.py for DEMO_MODE


NAMES_URL = "https://mesonet.agron.iastate.edu/json/webcams.php?network=IDOT"


def split_names(view_names: dict[int, str]) -> tuple[str | None, dict[int, str]]:
    """'Adair I80 North' / 'Adair I80 Bridge Deck' -> ('Adair I80', {0: 'North', 2: 'Bridge Deck'}).

    IEM's view names are inconsistent; a label that is empty, repeats the site name, is only a
    parenthetical like '(IA 4)', or duplicates another view's label falls back to 'View N'.
    """
    named = {i: n for i, n in view_names.items() if n}
    if not named:
        return None, {i: f"View {i + 1}" for i in view_names}
    words = [n.split() for n in named.values()]
    common = []
    for col in zip(*words):
        if len(set(col)) != 1:
            break
        common.append(col[0])
    site = " ".join(common) if common else min(named.values(), key=len)
    labels: dict[int, str] = {}
    seen: set[str] = set()
    for i in view_names:
        raw = named.get(i, "")
        rest = " ".join(raw.split()[len(common):]) if common and raw.startswith(site) else raw
        ok = rest and rest != site and not (rest.startswith("(") and rest.endswith(")")) and rest not in seen
        labels[i] = rest if ok else f"View {i + 1}"
        seen.add(labels[i])
    return site, labels


async def camera_names() -> dict[str, str]:
    """Per-view names keyed by view id (e.g. 'IDOT-000-03' -> 'Adair I80 East'). Cached for an hour
    (the directory only lists cameras currently reporting, so it changes through the day)."""
    try:
        r = await cache.get_json(NAMES_URL, ttl=3600)
    except cache.SourceUnavailable:
        return {}
    return {x["cid"]: x["name"] for x in r.data.get("images", []) if x.get("cid") and x.get("name")}


def cameras_url(as_of: datetime, live: bool | None = None) -> str:
    base = f"{IEM}/idot_rwiscam.geojson"
    live = (not is_historical(as_of)) if live is None else live
    return base if live else f"{base}?valid={iso_z(archive_time(as_of))}"


def image_time(url: str) -> datetime | None:
    m = IMAGE_URL.match(url or "")
    return datetime.strptime(m.group(1), "%Y%m%d%H%M").replace(tzinfo=timezone.utc) if m else None


def _km(lat: float, lon: float, lat0: float, lon0: float) -> float:
    return 111.2 * math.hypot(lat - lat0, (lon - lon0) * math.cos(math.radians(lat0)))


def _bearing(lat: float, lon: float, lat0: float, lon0: float) -> str:
    ang = math.degrees(math.atan2((lon - lon0) * math.cos(math.radians(lat0)), lat - lat0)) % 360
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((ang + 22.5) // 45) % 8]


def parse_cameras(geojson: dict, facility: Facility, as_of: datetime, live: bool, nearest: int = NEAREST,
                  names: dict[str, str] | None = None) -> list[dict]:
    """Nearest cameras to the facility with their views, dropping images taken after ``as_of``."""
    as_of = utc(as_of)
    out = []
    for f in geojson.get("features", []):
        geom = f.get("geometry")
        if not geom:
            continue
        lon, lat = geom["coordinates"][:2]
        p = f["properties"]
        views = []
        for i in range(10):
            url = p.get(f"imgurl{i}")
            t = image_time(url) if url else None
            if t is None or t > as_of + timedelta(minutes=1):
                continue  # unparseable, or newer than the moment being viewed
            if live and as_of - t > LIVE_MAX_AGE:
                continue  # stale feed: camera is effectively offline
            views.append({"view": i, "url": url, "time": t.isoformat()})
        if not views:
            continue
        cid = p.get("cid") or p.get("index")
        site, labels = split_names({v["view"]: (names or {}).get(f"{cid}-{v['view']:02d}", "") for v in views})
        if site is None:  # the directory sometimes names only a different view of this site
            site = next((n for k, n in (names or {}).items() if k.startswith(f"{cid}-")), None)
        for v in views:
            v["label"] = labels.get(v["view"]) or f"View {v['view'] + 1}"
        km = _km(lat, lon, facility.lat, facility.lon)
        corridor = next((c for c in facility.corridors
                         if point_to_polyline_km((lon, lat), c.coordinates) <= CORRIDOR_KM), None)
        out.append({
            "id": cid,
            "name": site or f"Iowa DOT camera {cid}",
            "lat": lat, "lon": lon,
            "km": round(km, 1),
            "direction": _bearing(lat, lon, facility.lat, facility.lon),
            "corridor": corridor.id if corridor else None,
            "corridor_name": corridor.name if corridor else None,
            "updated": max(v["time"] for v in views),
            "views": views,
        })
    out.sort(key=lambda c: c["km"])
    return out[:nearest]


async def fetch_cameras(facility: Facility, as_of: datetime, nearest: int = NEAREST,
                        live: bool | None = None) -> tuple[list[dict], cache.CachedResponse]:
    live = (not is_historical(as_of)) if live is None else live
    r = await cache.get_json(cameras_url(as_of, live), historical=not live, ttl=300)
    return parse_cameras(r.data, facility, as_of, live=live, nearest=nearest, names=await camera_names()), r


# ----------------------------------------------------------------------------- image cache

def image_path(url: str) -> Path:
    return IMAGE_DIR / f"{hashlib.sha1(url.encode()).hexdigest()}.jpg"


def is_cached(url: str) -> bool:
    return image_path(url).exists()


async def get_image(url: str) -> bytes | None:
    """Image bytes from the local cache, fetching (and caching) when allowed. None if unavailable."""
    if not IMAGE_URL.match(url or ""):
        raise ValueError("not an IEM camera image URL")
    path = image_path(url)
    if path.exists():
        return path.read_bytes()
    if settings.demo_mode:
        return None
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": settings.nws_user_agent}) as c:
            resp = await c.get(url)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image/"):
        return None
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(resp.content)
    tmp.replace(path)
    return resp.content


def save_demo_list(cams: list[dict], fetched_at: datetime) -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    (IMAGE_DIR / DEMO_LIST).write_text(json.dumps({"fetched_at": fetched_at.isoformat(), "cameras": cams}), encoding="utf-8")


def load_demo_list() -> tuple[list[dict], datetime] | None:
    """The live camera list pinned when images were cached, so demo list and images always match."""
    p = IMAGE_DIR / DEMO_LIST
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return d["cameras"], datetime.fromisoformat(d["fetched_at"])
