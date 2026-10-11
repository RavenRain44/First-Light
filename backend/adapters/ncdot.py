"""DriveNC's current, keyed feeds. No public historical road archive is verified.

The retired eapps.ncdot.gov traffic API now redirects users to these v2/v3
interfaces. Query credentials never appear in source URLs or persisted caches.
An empty incident feed does not mean every road has been inspected and is safe.
"""
from __future__ import annotations

import math
import os
import asyncio
from datetime import datetime, timezone

from adapters import cache
from adapters.base import Adapter, Facility, NormalizedInput, is_historical, utc
from adapters.iem_roads import MATCH_KM, point_to_polyline_km

API = "https://www.drivenc.gov/api"
EVENTS_URL = f"{API}/v2/get/event"
CONDITIONS_URL = f"{API}/v3/get/roadconditions"
CAMERAS_URL = f"{API}/v2/get/cameras"


async def get_feed(url: str, *, ttl: int = 300, allow_demo_bypass: bool = False) -> cache.CachedResponse:
    key = os.environ.get("NCDOT_API_KEY", "").strip()
    if not key:
        raise cache.SourceUnavailable("NCDOT_API_KEY is not configured. Official DriveNC roads and cameras are unavailable; missing reports do not mean roads are safe.")
    try:
        response = await asyncio.wait_for(cache.get_json(url, ttl=ttl, allow_demo_bypass=allow_demo_bypass,
                                         request_params={"key": key, "format": "json"}), timeout=20)
    except TimeoutError:
        raise cache.SourceUnavailable("DriveNC exceeded the 20-second source request budget.") from None
    if not isinstance(response.data, list):
        # Do not echo a provider error body: it could contain authentication data.
        raise cache.SourceUnavailable("DriveNC did not return the documented record list.")
    return response


def timestamp(value) -> datetime | None:
    try:
        if isinstance(value, bool) or value is None:
            return None
        return datetime.fromtimestamp(float(value), timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def number(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def decode_polyline(encoded: str) -> list[list[float]]:
    """Decode documented Google geometry, bounding work for malformed feeds."""
    out, idx, lat, lon = [], 0, 0, 0
    while idx < len(encoded) and len(out) < 5000:
        for axis in (0, 1):
            value, shift = 0, 0
            while True:
                if idx >= len(encoded) or shift > 30:
                    return []
                part = ord(encoded[idx]) - 63
                idx += 1
                if not 0 <= part <= 63:
                    return []
                value |= (part & 31) << shift
                shift += 5
                if part < 32:
                    break
            change = ~(value >> 1) if value & 1 else value >> 1
            if axis == 0:
                lat += change
            else:
                lon += change
        p = [lon / 1e5, lat / 1e5]
        if not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90):
            return []
        out.append(p)
    return out


def event_geometry(row: dict) -> dict | None:
    points = decode_polyline(row.get("EncodedPolyline") or "")
    if len(points) >= 2:
        return {"type": "LineString", "coordinates": points}
    lat, lon = number(row.get("Latitude")), number(row.get("Longitude"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    lat2, lon2 = number(row.get("LatitudeSecondary")), number(row.get("LongitudeSecondary"))
    if lat2 is not None and lon2 is not None and (lat2, lon2) != (lat, lon) and -90 <= lat2 <= 90 and -180 <= lon2 <= 180:
        return {"type": "LineString", "coordinates": [[lon, lat], [lon2, lat2]]}
    return {"type": "Point", "coordinates": [lon, lat]}


def event_hazard(row: dict) -> str:
    text = " ".join(str(row.get(k) or "") for k in ("Description", "EventSubType", "Comment", "OriginalEventType")).lower()
    if any(word in text for word in ("flood", "high water", "washout", "storm surge")):
        return "flood"
    if any(word in text for word in ("snow", "freezing", "icy", "ice ")):
        return "winter"
    if any(word in text for word in ("wind", "tree", "debris", "hurricane", "tropical")):
        return "wind"
    return "traffic"


def parse_events(rows: list[dict], facility: Facility, as_of: datetime) -> dict:
    features = []
    now = utc(as_of)
    for row in rows:
        reported, updated = timestamp(row.get("Reported")), timestamp(row.get("LastUpdated"))
        start, end = timestamp(row.get("StartDate")), timestamp(row.get("PlannedEndDate"))
        if updated is None or updated > now or (reported is not None and reported > now) or (start is not None and start > now) or (end is not None and end <= now):
            continue
        geometry = event_geometry(row)
        if geometry is None:
            continue
        pts = [geometry["coordinates"]] if geometry["type"] == "Point" else geometry["coordinates"]
        corridors = [c.id for c in facility.corridors if any(point_to_polyline_km(tuple(p), c.coordinates) <= MATCH_KM for p in pts)]
        if not corridors:
            continue
        # A closure event can mean a single lane closure. Only the provider's
        # full-closure flag establishes a closed road.
        full = row.get("IsFullClosure") is True
        rank = 5 if full else 4 if event_hazard(row) in ("flood", "winter", "wind") else 1
        label = "Road closed" if full else "Reported weather restriction" if rank == 4 else "Reported traffic restriction"
        properties = {"event_id": str(row.get("ID", "")), "provider": "NCDOT",
                      "label": label, "rank": rank, "rank_label": label,
                      "corridors": corridors, "utc_valid": updated.isoformat(),
                      "description": row.get("Description"), "roadway": row.get("RoadwayName"),
                      "native_severity": row.get("Severity"), "hazard": event_hazard(row),
                      "full_closure": full, "reported": reported.isoformat() if reported else None,
                      "source_url": "https://www.drivenc.gov/"}
        features.append({"type": "Feature", "id": properties["event_id"], "geometry": geometry, "properties": properties})
    return {"type": "FeatureCollection", "features": features,
            "coverage_note": "Only reported DriveNC events near configured corridors. No event is not an all-clear."}


async def fetch_road_geojson(facility: Facility, as_of: datetime, *, allow_demo_bypass: bool = False):
    if facility.state != "NC":
        raise cache.SourceUnavailable("DriveNC covers North Carolina only.")
    if is_historical(as_of):
        raise cache.SourceUnavailable("A time-versioned DriveNC road archive is unavailable; live roads are never substituted into replay.")
    requests = await asyncio.gather(get_feed(EVENTS_URL, allow_demo_bypass=allow_demo_bypass),
                                    get_feed(CONDITIONS_URL, allow_demo_bypass=allow_demo_bypass), return_exceptions=True)
    event_response, condition_response = requests
    if isinstance(event_response, Exception) and isinstance(condition_response, Exception):
        raise cache.SourceUnavailable(str(event_response))
    geo = parse_events(event_response.data if isinstance(event_response, cache.CachedResponse) else [], facility, as_of)
    counties = {c.casefold() for c in (getattr(facility, "provider_settings", {}) or {}).get("road_counties", [])}
    reports = []
    if isinstance(condition_response, cache.CachedResponse):
        for row in condition_response.data:
            updated = timestamp(row.get("LastUpdated"))
            county = str(row.get("County") or "")
            if county.casefold() not in counties or updated is None or updated > utc(as_of):
                continue
            reports.append({"county": county, "location": row.get("LocationDescription"),
                            "overall": row.get("Overall for Public Display"), "interstates": row.get("Interstates"),
                            "us_nc_routes": row.get("US/NC Routes"), "secondary_roads": row.get("Secondary Roads"),
                            "utc_valid": updated.isoformat(), "source_url": CONDITIONS_URL,
                            "fetched_at": condition_response.fetched_at.isoformat()})
    geo["county_reports"] = reports
    geo["events_available"] = isinstance(event_response, cache.CachedResponse)
    geo["county_conditions_available"] = isinstance(condition_response, cache.CachedResponse)
    response = event_response if isinstance(event_response, cache.CachedResponse) else condition_response
    return geo, response


class NCDOTRoadsAdapter(Adapter):
    name = "ncdot_roads"
    label = "NCDOT DriveNC road events"
    coverage = "NC"
    supports_historical = False

    def __init__(self, allow_demo_bypass: bool = False):
        self.allow_demo_bypass = allow_demo_bypass

    async def fetch(self, facility: Facility, as_of: datetime) -> list[NormalizedInput]:
        self._urls.extend((EVENTS_URL, CONDITIONS_URL))
        geo, response = await fetch_road_geojson(facility, as_of, allow_demo_bypass=self.allow_demo_bypass)
        out = []
        for corridor in facility.corridors:
            reports = [f["properties"] for f in geo["features"] if corridor.id in f["properties"]["corridors"]]
            if not reports:
                continue  # Silence is unknown, not a zero/normal road condition.
            worst = max(reports, key=lambda r: r["rank"])
            out.append(NormalizedInput(
                id=f"road.{corridor.id}", kind="road", role="observation", metric="road_condition_rank", unit="rank",
                value=worst["rank"], data={"corridor": corridor.id, "name": corridor.name,
                    "provider": "NCDOT", "label": worst["label"], "rank_label": worst["rank_label"],
                    "hazard": worst["hazard"], "n_segments": len(reports), "event_ids": [r["event_id"] for r in reports],
                    "reports": reports, "coverage_note": geo["coverage_note"]},
                source=self.label, source_url=EVENTS_URL, fetched_at=response.fetched_at,
                source_time=datetime.fromisoformat(worst["utc_valid"]),
                note="Reported restriction on a configured corridor; ranks are application policy, not an Iowa winter condition.",
            ))
        for n, report in enumerate(geo.get("county_reports", [])):
            out.append(NormalizedInput(id=f"road.county.{report['county'].replace(' ', '_')}.{n}", kind="report", role="context",
                metric="road_county_report", value=report.get("overall") or report.get("location"), data={**report,"provider":"NCDOT"},
                source="NCDOT county road conditions", source_url=CONDITIONS_URL, fetched_at=datetime.fromisoformat(report["fetched_at"]),
                source_time=datetime.fromisoformat(report["utc_valid"]),
                note="County-scale official report, not a sensor reading or verified condition on every commute segment."))
        return out
