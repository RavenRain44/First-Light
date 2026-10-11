"""Iowa DOT traffic cameras (511 network): locations, live HLS video and current snapshots.

For human situational awareness only, like the RWIS cameras in ``iem_cameras``: not an input
to the recommendation and not stored on snapshots. These are the freeway cameras around Ames
(US 30 west to Boone and east to Nevada, I-35 south to Ankeny and north to Ellsworth), much
closer to the facility than any RWIS camera, and most of them publish a live HLS stream.
Iowa DOT has none on Ames city streets or north/west of town short of those corridors. Iowa DOT keeps no public archive, so they are live-only; Replay
keeps using the RWIS archive.

Locations come from Iowa DOT's open-data feature service (updated daily). Stream and snapshot
URLs are always taken from that feed, never built by hand: Iowa DOT has been moving video
hosts (video4.iowadot.gov -> video.iowadot.gov in 2026).
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlencode

from adapters import cache
from adapters.base import Facility
from adapters.iem_cameras import _bearing, _km
from adapters.iem_roads import point_to_polyline_km

FEATURES = "https://services.arcgis.com/8lRhdTsQyJpO52F1/arcgis/rest/services/Traffic_Cameras_View/FeatureServer/0/query"
RADIUS_KM = 40  # far enough to reach a camera north of Ames (I-35 at Ellsworth, ~32 km)
NEAREST = 20
SPREAD_KM = 20  # beyond the nearest camera in each direction, stay this close
RWIS_NEAREST = 5  # RWIS sites kept alongside them in live view (the nearest is ~50 km out)
SAME_SPOT_KM = 0.15  # cameras this close are the same pole (wrong-way / alternate feeds); keep one
CORRIDOR_KM = 2.0
VIDEO_URL = re.compile(r"^https://video\d*\.iowadot\.gov(:\d+)?/[A-Za-z0-9_/-]+\.m3u8$")
SNAPSHOT_URL = re.compile(r"^https://atmsqf\.iowadot\.gov/SNAPSHOTS/PUBLIC/[A-Za-z0-9_/-]+\.jpe?g$")
FIELDS = "COMMON_ID,Desc_,Route,ImageURL,VideoURL,latitude,longitude,FUNCTION"


def features_url(facility: Facility, radius_km: float = RADIUS_KM) -> str:
    return FEATURES + "?" + urlencode({
        "where": "1=1", "geometry": f"{facility.lon},{facility.lat}", "geometryType": "esriGeometryPoint",
        "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "distance": radius_km,
        "units": "esriSRUnit_Kilometer", "outFields": FIELDS, "returnGeometry": "false", "f": "json",
    })


def _name(desc: str) -> str:
    """'AM - US 30 @ MM 147 (University Blvd)' -> 'US 30 @ MM 147 (University Blvd)'."""
    return re.sub(r"^[A-Z0-9]{1,4} - ", "", desc.strip())


def _secondary(a: dict) -> bool:
    """Wrong-way-detection and '-Q' alternate feeds duplicate a general camera on the same pole."""
    return a.get("FUNCTION") != "General" or str(a.get("COMMON_ID", "")).endswith("Q")


def spread(cams: list[dict], n: int) -> list[dict]:
    """Up to ``n`` cameras spread around the facility: take turns across the compass directions,
    nearest first in each, so one busy interchange can't fill the list. Every direction gets its
    nearest camera however far; after that only cameras within SPREAD_KM are added."""
    by_dir: dict[str, list[dict]] = {}
    for c in sorted(cams, key=lambda c: c["km"]):
        by_dir.setdefault(c["direction"], []).append(c)
    picked = [q.pop(0) for q in by_dir.values()][:n]
    queues = [[c for c in q if c["km"] <= SPREAD_KM] for q in by_dir.values()]
    while len(picked) < n and any(queues):
        for q in queues:
            if q and len(picked) < n:
                picked.append(q.pop(0))
    return sorted(picked, key=lambda c: c["km"])


def parse_traffic_cameras(data: dict, facility: Facility, fetched_at: datetime, nearest: int = NEAREST) -> list[dict]:
    """Video cameras spread around the facility, one per location, in the same shape as RWIS cameras."""
    rows = []
    for f in data.get("features", []):
        a = f.get("attributes") or {}
        video, snap = a.get("VideoURL") or "", a.get("ImageURL") or ""
        if not (VIDEO_URL.match(video) and SNAPSHOT_URL.match(snap)):
            continue  # no live video (e.g. rest-area parking cameras), or a URL we won't serve
        if a.get("latitude") is None or a.get("longitude") is None:
            continue
        rows.append(a)
    rows.sort(key=_secondary)  # general cameras claim a location before their duplicates
    out: list[dict] = []
    for a in rows:
        lat, lon = float(a["latitude"]), float(a["longitude"])
        if any(_km(lat, lon, c["lat"], c["lon"]) < SAME_SPOT_KM for c in out):
            continue
        corridor = next((c for c in facility.corridors
                         if point_to_polyline_km((lon, lat), c.coordinates) <= CORRIDOR_KM), None)
        t = fetched_at.isoformat()
        out.append({
            "id": a["COMMON_ID"],
            "kind": "traffic",
            "name": _name(a.get("Desc_") or a["COMMON_ID"]),
            "lat": lat, "lon": lon,
            "km": round(_km(lat, lon, facility.lat, facility.lon), 1),
            "direction": _bearing(lat, lon, facility.lat, facility.lon),
            "corridor": corridor.id if corridor else None,
            "corridor_name": corridor.name if corridor else None,
            "updated": t,
            "stream_url": a["VideoURL"],
            "snapshot_url": a["ImageURL"],
            "views": [{"view": 0, "url": a["ImageURL"], "time": t, "label": "Live"}],
        })
    return spread(out, nearest)


async def fetch_traffic_cameras(facility: Facility, nearest: int = NEAREST) -> tuple[list[dict], cache.CachedResponse]:
    r = await cache.get_json(features_url(facility), ttl=3600)
    if "error" in r.data:  # ArcGIS reports query errors with HTTP 200
        raise cache.SourceUnavailable(f"Iowa DOT camera feed error: {r.data['error']}")
    return parse_traffic_cameras(r.data, facility, r.fetched_at, nearest=nearest), r


def merge_live(rwis: list[dict], traffic: list[dict], webcams: list[dict] = ()) -> list[dict]:
    """Live camera list: traffic cameras, nearby webcams, and a few RWIS sites (pavement/weather views)."""
    rwis = rwis[:RWIS_NEAREST] if traffic else rwis
    return sorted([*traffic, *webcams, *rwis], key=lambda c: c["km"])
