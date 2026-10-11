"""National Weather Service API (api.weather.gov) adapters: point metadata,
active alerts and raw forecast grids. NWS keeps no archive, so these are live-only."""
from __future__ import annotations

from datetime import datetime, timedelta

from adapters import cache
from adapters.base import Adapter, Facility, NormalizedInput, Point, floor_hour, utc
from engine.normalize import expand_grid_element

API = "https://api.weather.gov"

# NWS element -> (our metric id, unit)
GRID_ELEMENTS = {
    "windGust": "wind_gust_mph",
    "windSpeed": "wind_speed_mph",
    "temperature": "temp_f",
    "apparentTemperature": "apparent_temp_f",
    "iceAccumulation": "ice_in",
    "snowfallAmount": "snow_in",
    "quantitativePrecipitation": "qpf_in",
    "probabilityOfPrecipitation": "pop_pct",
    "skyCover": "sky_cover_pct",
}
UNITS = {"wind_gust_mph": "mph", "wind_speed_mph": "mph", "temp_f": "degF", "apparent_temp_f": "degF",
         "ice_in": "in", "snow_in": "in", "qpf_in": "in", "pop_pct": "%", "sky_cover_pct": "%"}


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


async def resolve_point(lat: float, lon: float, *, allow_demo_bypass: bool = False) -> tuple[dict, cache.CachedResponse]:
    """GET /points/{lat},{lon}: grid id/x/y, forecast zone, county, stations. Cached for a day."""
    url = f"{API}/points/{lat:.4f},{lon:.4f}"
    r = await cache.get_json(url, ttl=86400, allow_demo_bypass=allow_demo_bypass)
    p = r.data["properties"]
    meta = {
        "gridId": p["gridId"],
        "gridX": p["gridX"],
        "gridY": p["gridY"],
        "forecastGridData": p["forecastGridData"],
        "forecastZone": p["forecastZone"].rsplit("/", 1)[-1],
        "county": p["county"].rsplit("/", 1)[-1],
        "cwa": p.get("cwa"),
        "timeZone": p.get("timeZone"),
        "city": (p.get("relativeLocation") or {}).get("properties", {}).get("city"),
        "state": (p.get("relativeLocation") or {}).get("properties", {}).get("state"),
    }
    return meta, r


def alert_from_feature(feature: dict) -> dict:
    p = feature["properties"]
    return {
        "id": p["id"],
        "event": p.get("event"),
        "severity": p.get("severity"),
        "certainty": p.get("certainty"),
        "urgency": p.get("urgency"),
        "onset": p.get("onset"),
        "ends": p.get("ends"),
        "expires": p.get("expires"),
        "effective": p.get("effective"),
        "sent": p.get("sent"),
        "headline": p.get("headline"),
        "description": p.get("description"),
        "instruction": p.get("instruction"),
        "areaDesc": p.get("areaDesc"),
        "senderName": p.get("senderName"),
        "messageType": p.get("messageType"),
        "status": p.get("status"),
        "vtec": (p.get("parameters") or {}).get("VTEC", []),
        "ugc": (p.get("geocode") or {}).get("UGC", []),
        "web": p.get("@id"),
        "origin": "nws_api",
    }


class NWSAlertsAdapter(Adapter):
    name = "nws_alerts"
    label = "NWS active alerts"
    supports_historical = False
    coverage = "US"

    def __init__(self, allow_demo_bypass: bool = False):
        self.allow_demo_bypass = allow_demo_bypass

    async def fetch(self, facility: Facility, as_of: datetime) -> list[NormalizedInput]:
        url = f"{API}/alerts/active?point={facility.lat:.4f},{facility.lon:.4f}"
        self._urls.append(url)
        r = await cache.get_json(url, allow_demo_bypass=self.allow_demo_bypass, ttl=120)
        out = []
        for f in r.data.get("features", []):
            a = alert_from_feature(f)
            if a["status"] not in (None, "Actual") or a["event"] == "Test Message":
                continue
            out.append(NormalizedInput(
                id=f"alert:{a['id']}", kind="alert", role="alert", metric="nws_alert", value=a["event"],
                data=a, source="NWS API /alerts/active", source_url=url, fetched_at=r.fetched_at,
                source_time=_dt(a["sent"]),
            ))
        if not out:
            # An empty alert list is real information ("no alerts in effect"), not a missing source.
            out.append(NormalizedInput(
                id="alert:none", kind="scalar", role="alert", metric="nws_alert_count", value=0.0, unit="count",
                source="NWS API /alerts/active", source_url=url, fetched_at=r.fetched_at,
                note="No active NWS alerts for this point",
            ))
        return out


class NWSGridAdapter(Adapter):
    name = "nws_grid"
    label = "NWS gridded forecast"
    supports_historical = False
    coverage = "US"

    def __init__(self, allow_demo_bypass: bool = False, hours_ahead: int = 72):
        self.allow_demo_bypass = allow_demo_bypass
        self.hours_ahead = hours_ahead

    async def fetch(self, facility: Facility, as_of: datetime) -> list[NormalizedInput]:
        meta, pr = await resolve_point(facility.lat, facility.lon, allow_demo_bypass=self.allow_demo_bypass)
        self._urls.append(pr.url)
        url = meta["forecastGridData"]
        self._urls.append(url)
        r = await cache.get_json(url, allow_demo_bypass=self.allow_demo_bypass)
        props = r.data["properties"]
        update_time = _dt(props.get("updateTime"))
        start = floor_hour(as_of) - timedelta(hours=1)
        end = floor_hour(as_of) + timedelta(hours=self.hours_ahead + 1)
        out: list[NormalizedInput] = []
        for element, metric in GRID_ELEMENTS.items():
            el = props.get(element)
            if not el or not el.get("values"):
                continue
            pts = [Point(t=t, v=None if v is None else round(v, 3))
                   for t, v in expand_grid_element(element, el["values"], el.get("uom"))
                   if start <= t < end]
            out.append(NormalizedInput(
                # Sky cover is presentation context, excluded from scoring and confidence.
                id=f"fcst.{metric}", kind="series", metric=metric, unit=UNITS[metric],
                role="context" if metric == "sky_cover_pct" else "forecast",
                series=pts, source=f"NWS gridpoints {meta['gridId']}/{meta['gridX']},{meta['gridY']}",
                source_url=url, fetched_at=r.fetched_at, source_time=update_time,
                note=f"{element} ({el.get('uom')}) expanded from ISO-8601 intervals to hourly",
            ))
        out.append(NormalizedInput(
            id="nws.point", kind="scalar", role="context", metric="nws_point", value=meta["forecastZone"],
            data=meta, source="NWS API /points", source_url=pr.url, fetched_at=pr.fetched_at,
        ))
        return out
