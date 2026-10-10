"""Iowa DOT winter road conditions and RWIS pavement sensors, via the IEM archive.

Road segments carry no route names, so they are matched to the facility's
commute corridors by geometry: a segment belongs to a corridor when most of
its vertices lie within ``MATCH_KM`` of the corridor polyline.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from adapters import cache
from adapters.base import Adapter, Corridor, Facility, NormalizedInput, is_historical, iso_z, utc

IEM = "https://mesonet.agron.iastate.edu/api/1"
TRIM_DEG = 0.6
MATCH_KM = 2.0
MATCH_FRACTION = 0.6

# Ordinal severity used for "worst condition". Category names come from Iowa DOT
# (as archived by IEM); the ordering is ours and is documented in thresholds.yaml.
RANK_LABELS = {
    0: "Seasonal / normal",
    1: "Wet or frost",
    2: "Partially covered",
    3: "Completely covered",
    4: "Travel advisory",
    5: "Travel not advised / closed",
}


def road_rank(label: str | None) -> int | None:
    if not label:
        return None
    s = label.lower()
    if any(k in s for k in ("impassable", "closed", "not advised", "no travel")):
        return 5
    if "travel advisory" in s:
        return 4
    if "frost" in s:
        return 1
    if s.startswith("cc") or "completely" in s:
        return 3
    if s.startswith("pc") or "partially" in s:
        return 2
    if "wet" in s:
        return 1
    if any(k in s for k in ("normal", "seasonal", "dry")):
        return 0
    return None


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Equirectangular distance in km between (lon, lat) points; fine at corridor scale."""
    lat = math.radians((a[1] + b[1]) / 2)
    dx = math.radians(b[0] - a[0]) * math.cos(lat)
    dy = math.radians(b[1] - a[1])
    return 6371.0 * math.hypot(dx, dy)


def point_to_polyline_km(p: tuple[float, float], line: list[list[float]]) -> float:
    best = float("inf")
    lat0 = math.radians(p[1])
    kx, ky = 111.32 * math.cos(lat0), 110.57
    px, py = p[0] * kx, p[1] * ky
    for (x1, y1), (x2, y2) in zip(line, line[1:]):
        ax, ay, bx, by = x1 * kx, y1 * ky, x2 * kx, y2 * ky
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return best


def _flatten(geom: dict) -> list[tuple[float, float]]:
    c = geom["coordinates"]
    if geom["type"] == "LineString":
        return [tuple(p) for p in c]
    if geom["type"] == "MultiLineString":
        return [tuple(p) for line in c for p in line]
    return []


def match_corridors(geom: dict, corridors: list[Corridor]) -> list[str]:
    pts = _flatten(geom)
    if not pts:
        return []
    step = max(1, len(pts) // 25)  # sample long segments
    sample = pts[::step]
    out = []
    for c in corridors:
        near = sum(1 for p in sample if point_to_polyline_km(p, c.coordinates) <= MATCH_KM)
        if near / len(sample) >= MATCH_FRACTION:
            out.append(c.id)
    return out


def _thin(line: list, max_pts: int = 40) -> list:
    step = max(1, len(line) // max_pts)
    keep = line[::step]
    if keep[-1] != line[-1]:
        keep.append(line[-1])
    return [[round(x, 4), round(y, 4)] for x, y in keep]


def simplify(geom: dict) -> dict:
    """Round to ~10 m and keep <= ~40 vertices per line: plenty for corridor matching and the map."""
    if geom["type"] == "LineString":
        return {"type": "LineString", "coordinates": _thin(geom["coordinates"])}
    if geom["type"] == "MultiLineString":
        return {"type": "MultiLineString", "coordinates": [_thin(line) for line in geom["coordinates"]]}
    return geom


def _trim_near(lat: float, lon: float):
    def trim(data: dict) -> dict:
        feats = []
        for f in data.get("features", []):
            pts = _flatten(f.get("geometry") or {"type": "x", "coordinates": []})
            if any(abs(p[1] - lat) < TRIM_DEG and abs(p[0] - lon) < TRIM_DEG for p in pts):
                feats.append({**f, "geometry": simplify(f["geometry"])})
        return {"type": "FeatureCollection", "features": feats}
    return trim


ARCHIVE_STEP_HOURS = 3  # archive lookups are floored to a 3-hour grid to keep backtests light on IEM


def archive_time(as_of: datetime) -> datetime:
    t = utc(as_of).replace(minute=0, second=0, microsecond=0)
    return t.replace(hour=t.hour - t.hour % ARCHIVE_STEP_HOURS)


def roads_url(as_of: datetime) -> str:
    base = f"{IEM}/iowa_winter_roadcond.geojson"
    return f"{base}?valid={iso_z(archive_time(as_of))}" if is_historical(as_of) else base


async def fetch_road_geojson(facility: Facility, as_of: datetime) -> tuple[dict, cache.CachedResponse]:
    """Trimmed segment GeoJSON with rank + corridor matches added to each feature."""
    url = roads_url(as_of)
    r = await cache.get_json(url, historical=is_historical(as_of),
                             trim=(f"near:{facility.lat:.2f},{facility.lon:.2f}", _trim_near(facility.lat, facility.lon)))
    feats = []
    for i, f in enumerate(r.data.get("features", [])):
        p = dict(f["properties"])
        p["segment_id"] = f.get("id", p.get("int1", i))
        p["rank"] = road_rank(p.get("label"))
        p["rank_label"] = RANK_LABELS.get(p["rank"]) if p["rank"] is not None else "No report"
        p["corridors"] = match_corridors(f["geometry"], facility.corridors)
        feats.append({"type": "Feature", "geometry": f["geometry"], "properties": p})
    return {"type": "FeatureCollection", "features": feats}, r


class IEMRoadsAdapter(Adapter):
    name = "iem_roads"
    label = "Iowa DOT road conditions (IEM)"
    supports_historical = True
    coverage = "IA"

    async def fetch(self, facility: Facility, as_of: datetime) -> list[NormalizedInput]:
        if utc(as_of).month in (5, 6, 7, 8, 9):
            return []  # Iowa DOT winter road reporting is seasonal; skip the call in summer
        self._urls.append(roads_url(as_of))
        gj, r = await fetch_road_geojson(facility, as_of)
        segs = [f["properties"] for f in gj["features"]]
        if not segs:
            return []
        out = []
        worst_overall: tuple[int, str] | None = None
        for c in facility.corridors:
            mine = [s for s in segs if c.id in s["corridors"] and s["rank"] is not None]
            if not mine:
                out.append(NormalizedInput(
                    id=f"road.{c.id}", kind="road", role="observation", metric="road_condition_rank",
                    unit="rank", value=None, data={"corridor": c.id, "name": c.name, "n_segments": 0},
                    source="Iowa DOT via IEM iowa_winter_roadcond", source_url=r.url, fetched_at=r.fetched_at,
                    note="no matched segments reporting",
                ))
                continue
            w = max(mine, key=lambda s: s["rank"])
            updated = max(datetime.fromisoformat(s["utc_valid"].replace("Z", "+00:00")) for s in mine if s.get("utc_valid"))
            out.append(NormalizedInput(
                id=f"road.{c.id}", kind="road", role="observation", metric="road_condition_rank", unit="rank",
                value=float(w["rank"]),
                data={"corridor": c.id, "name": c.name, "label": w["label"], "rank_label": w["rank_label"],
                      "n_segments": len(mine), "labels": sorted({s["label"] for s in mine})},
                source="Iowa DOT via IEM iowa_winter_roadcond", source_url=r.url, fetched_at=r.fetched_at,
                source_time=updated.astimezone(timezone.utc),
            ))
            if worst_overall is None or w["rank"] > worst_overall[0]:
                worst_overall = (w["rank"], c.id)
        return out


def _trim_rwis(lat: float, lon: float):
    def trim(data: dict) -> dict:
        rows = [d for d in data.get("data", [])
                if d.get("network") == "IA_RWIS" and d.get("lat") is not None
                and abs(d["lat"] - lat) < TRIM_DEG and abs(d["lon"] - lon) < TRIM_DEG]
        return {"data": rows}
    return trim


class IEMRWISAdapter(Adapter):
    name = "iem_rwis"
    label = "Iowa DOT RWIS pavement sensors (IEM)"
    supports_historical = True
    coverage = "IA"
    radius_km = 40.0

    async def fetch(self, facility: Facility, as_of: datetime) -> list[NormalizedInput]:
        hist = is_historical(as_of)
        url = f"{IEM}/rwis.json" + (f"?valid={iso_z(archive_time(as_of))}" if hist else "")
        self._urls.append(url)
        r = await cache.get_json(url, historical=hist,
                                 trim=(f"ia_near:{facility.lat:.2f},{facility.lon:.2f}", _trim_rwis(facility.lat, facility.lon)))
        rows = [d for d in r.data.get("data", [])
                if _km((facility.lon, facility.lat), (d["lon"], d["lat"])) <= self.radius_km]
        if not rows:
            return []
        temps = [(d["tfs0"], d) for d in rows if d.get("tfs0") is not None]
        texts = [(d.get(f"tfs{i}_text") or "") for d in rows for i in range(4)]
        ice = sum(1 for t in texts if "ice" in t.lower())
        newest = max(datetime.fromisoformat(d["utc_valid"].replace("Z", "+00:00")) for d in rows)
        stations = [{"station": d["station"], "name": d["name"], "pavement_f": d.get("tfs0"),
                     "condition": d.get("tfs0_text"), "air_f": d.get("tmpf"), "utc_valid": d["utc_valid"]} for d in rows]
        out = [NormalizedInput(
            id="rwis.ice_condition_sensors", kind="scalar", role="observation", metric="rwis_ice_sensor_count",
            unit="count", value=float(ice), data={"stations": stations},
            source="Iowa DOT RWIS via IEM", source_url=url, fetched_at=r.fetched_at, source_time=newest,
            note=f"pavement sensors within {self.radius_km:.0f} km reporting an ice watch/warning condition",
        )]
        if temps:
            t, d = min(temps, key=lambda x: x[0])
            out.append(NormalizedInput(
                id="rwis.min_pavement_temp_f", kind="scalar", role="observation", metric="pavement_temp_f",
                unit="degF", value=round(t, 1), data={"station": d["station"], "name": d["name"]},
                source="Iowa DOT RWIS via IEM", source_url=url, fetched_at=r.fetched_at, source_time=newest,
            ))
        return out
