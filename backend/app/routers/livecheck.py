"""Live Check: run the same engine against a what-if copy of the facility placed
at a currently active NWS alert anywhere in the US. Always live (bypasses
DEMO_MODE) and outside the Iowa scope, so Iowa-only sources are unavailable and
confidence drops accordingly."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from adapters import cache
from adapters.nws import API, alert_from_feature, resolve_point
from app import snapshots
from app.facility import load_facility
from engine.scoring import load_thresholds

router = APIRouter(prefix="/api/live-check")

MARINE_PREFIXES = ("AM", "AN", "GM", "LC", "LE", "LH", "LM", "LO", "LS", "PH", "PK", "PM", "PS", "PZ", "SL")
HANDLED = ("Winter", "Ice", "Blizzard", "Snow", "Wind", "Thunderstorm", "Tornado", "Cold", "Chill")
SEV_ORDER = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3, "Unknown": 4}


def _land(zone_url: str) -> bool:
    zid = zone_url.rsplit("/", 1)[-1]
    return not zid[:2] in MARINE_PREFIXES


def _centroid(geom: dict | None) -> tuple[float, float] | None:
    if not geom:
        return None
    coords = geom["coordinates"]
    if geom["type"] == "Polygon":
        ring = coords[0]
    elif geom["type"] == "MultiPolygon":
        ring = max((p[0] for p in coords), key=len)
    else:
        return None
    lon = sum(p[0] for p in ring) / len(ring)
    lat = sum(p[1] for p in ring) / len(ring)
    return lat, lon


async def _national() -> tuple[list[dict], datetime]:
    r = await cache.get_json(f"{API}/alerts/active?status=actual", allow_demo_bypass=True, ttl=120)
    return r.data.get("features", []), r.fetched_at


@router.get("/alerts")
async def alerts(limit: int = 150, facility_id: str | None = None):
    try:
        facility = load_facility(facility_id)
    except KeyError:
        raise HTTPException(404, "Unknown facility") from None
    configured_events = {event for rule in load_thresholds(facility=facility).rules for event in rule.events or []}
    try:
        feats, fetched = await _national()
    except cache.SourceUnavailable as e:
        raise HTTPException(503, f"NWS national alerts unavailable: {e}")
    out, seen = [], set()
    for f in feats:
        a = alert_from_feature(f)
        zones = f["properties"].get("affectedZones", [])
        if a["event"] == "Test Message" or not any(_land(z) for z in zones):
            continue
        key = (a["event"], a["areaDesc"], a["onset"])
        if key in seen:  # NWS often has an original and an update message for the same event
            continue
        seen.add(key)
        c = _centroid(f.get("geometry"))
        out.append({k: a[k] for k in ("id", "event", "severity", "certainty", "urgency", "onset", "ends", "expires",
                                      "headline", "areaDesc", "senderName")} |
                   {"has_geometry": c is not None, "handled_hazard": a["event"] in configured_events,
                    "n_zones": len(zones)})
    out.sort(key=lambda a: (not a["handled_hazard"], SEV_ORDER.get(a["severity"] or "Unknown", 4), a["event"]))
    return {"facility_id": facility.id, "fetched_at": fetched.isoformat(), "source_url": f"{API}/alerts/active?status=actual",
            "count": len(out), "alerts": out[:limit]}


class LiveCheckIn(BaseModel):
    facility_id: str | None = None
    alert_id: str
    assume_workday: bool = True  # what-if: treat every day (incl. weekends) as a workday


@router.post("/evaluate")
async def evaluate(req: LiveCheckIn, facility_id: str | None = None):
    if req.facility_id and facility_id and req.facility_id != facility_id:
        raise HTTPException(422, "Facility identifiers disagree")
    try:
        base = load_facility(req.facility_id or facility_id)
    except KeyError:
        raise HTTPException(404, "Unknown facility") from None
    try:
        feats, _ = await _national()
    except cache.SourceUnavailable as e:
        raise HTTPException(503, f"NWS national alerts unavailable: {e}")
    feat = next((f for f in feats if f["properties"]["id"] == req.alert_id), None)
    if feat is None:
        raise HTTPException(404, "alert is no longer active")
    loc = _centroid(feat.get("geometry"))
    if loc is None:
        for z in feat["properties"].get("affectedZones", []):
            if not _land(z):
                continue
            try:
                zr = await cache.get_json(z, allow_demo_bypass=True, ttl=86400)
            except cache.SourceUnavailable:
                continue
            loc = _centroid(zr.data.get("geometry"))
            if loc:
                break
    if loc is None:
        raise HTTPException(422, "could not locate this alert (no polygon and no land zone geometry)")
    lat, lon = round(loc[0], 4), round(loc[1], 4)
    try:
        meta, _ = await resolve_point(lat, lon, allow_demo_bypass=True)
    except cache.SourceUnavailable as e:
        raise HTTPException(422, f"NWS /points has no forecast grid at {lat},{lon}: {e}")
    place = ", ".join(x for x in (meta.get("city"), meta.get("state")) if x) or f"{lat},{lon}"
    what_if = base.model_copy(update={
        "id": "WHATIF-" + hashlib.sha1(f"{base.id}:{req.alert_id}".encode()).hexdigest()[:10],
        "name": f"What-if copy of {base.name.split(' (')[0]} placed near {place}",
        "lat": lat, "lon": lon, "state": meta.get("state") or "US", "timezone": meta.get("timeZone") or base.timezone,
        "asos_station": None, "mos_station": None, "nws_office": meta.get("cwa"), "corridors": [],
        "accessibility_notes": [], "hypothetical": True,
        "warning_ugcs": [meta["forecastZone"], meta["county"]],
        "forecast_zone": meta["forecastZone"], "county_ugc": meta["county"],
        "water_gauges": [], "coastal_gauge_ids": [],
        "provider_settings": {"origin_facility_id": base.id},
        "workdays": list(range(7)) if req.assume_workday else base.workdays,
    })
    snap = await snapshots.evaluate(what_if, datetime.now(timezone.utc), "livecheck")
    snap["livecheck"] = {"alert_id": req.alert_id, "event": feat["properties"]["event"], "place": place,
                         "base_facility_id": base.id,
                         "label": "Hypothetical location; source coverage and confidence follow the evaluated location",
                         "assume_workday": req.assume_workday}
    return snap
