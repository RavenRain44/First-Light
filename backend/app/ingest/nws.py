from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from dateutil.parser import isoparse

from backend.app.ingest.archive import Archive
from backend.app.ingest.http import CachedHTTPClient
from backend.app.models import AlertSignal, EvidenceItem, Facility, Hazard, MetricReading


def _dt(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    return isoparse(value).astimezone(UTC)


def _duration(value: str) -> timedelta:
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", value)
    if not match:
        return timedelta(hours=1)
    days, hours, minutes = (int(item or 0) for item in match.groups())
    return timedelta(days=days, hours=hours, minutes=minutes)


def _valid_time(value: str, fallback: datetime) -> tuple[datetime, datetime]:
    if "/" not in value:
        return fallback, fallback + timedelta(hours=1)
    start, duration = value.split("/", 1)
    parsed = _dt(start, fallback)
    return parsed, parsed + _duration(duration)


def _to_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("value", "maxValue", "minValue"):
            if isinstance(value.get(key), (int, float)):
                return float(value[key])
    return None


class NWSClient:
    base_url = "https://api.weather.gov"

    def __init__(self, http: CachedHTTPClient, archive: Archive) -> None:
        self.http = http
        self.archive = archive

    async def active_alerts(
        self, facility: Facility
    ) -> tuple[list[EvidenceItem], list[AlertSignal]]:
        url = f"{self.base_url}/alerts/active?point={facility.lat},{facility.lon}&status=actual"
        payload, cached = await self.http.get_json(url)
        fetched = datetime.now(UTC)
        digest, key = self.archive.put("nws-alerts", payload)
        features = payload.get("features", [])
        issued_values = [
            _dt(feature.get("properties", {}).get("sent"), fetched) for feature in features
        ]
        item = EvidenceItem(
            id=f"nws-alerts-{digest[:12]}",
            source="NWS alerts",
            url=url,
            issued_at=max(issued_values, default=fetched),
            fetched_at=fetched,
            sha256=digest,
            object_key=key,
            fields_used={"feature_count": len(features)},
            stale=cached,
        )
        alerts: list[AlertSignal] = []
        for feature in features:
            props = feature.get("properties", {})
            geocode = props.get("geocode") or {}
            zones = (geocode.get("UGC") or []) + [
                zone.rsplit("/", 1)[-1] for zone in props.get("affectedZones", [])
            ]
            onset = _dt(props.get("onset") or props.get("effective"), fetched)
            ends = _dt(props.get("ends") or props.get("expires"), onset + timedelta(hours=6))
            alerts.append(
                AlertSignal(
                    evidence_id=item.id,
                    event=props.get("event", "Weather Alert"),
                    severity=props.get("severity", "Unknown"),
                    certainty=props.get("certainty", "Unknown"),
                    urgency=props.get("urgency", "Unknown"),
                    onset=onset,
                    ends=ends,
                    headline=props.get("headline") or "",
                    description=props.get("description") or "",
                    instruction=props.get("instruction") or "",
                    area_desc=props.get("areaDesc") or "",
                    ugc_zones=zones,
                    parameters=props.get("parameters") or {},
                    covers_facility=not zones or bool(set(zones) & set(facility.ugc_zones)),
                )
            )
        return [item], alerts

    async def gridpoint(self, facility: Facility) -> tuple[list[EvidenceItem], list[MetricReading]]:
        point_url = f"{self.base_url}/points/{facility.lat},{facility.lon}"
        point, point_cached = await self.http.get_json(point_url, "application/geo+json")
        grid_url = point["properties"]["forecastGridData"]
        grid, grid_cached = await self.http.get_json(grid_url, "application/geo+json")
        fetched = datetime.now(UTC)
        digest, key = self.archive.put("nws-gridpoints", grid)
        updated = _dt(grid.get("properties", {}).get("updateTime"), fetched)
        item = EvidenceItem(
            id=f"nws-grid-{digest[:12]}",
            source="NWS gridpoints",
            url=grid_url,
            issued_at=updated,
            fetched_at=fetched,
            sha256=digest,
            object_key=key,
            fields_used={
                "iceAccumulation": True,
                "snowfallAmount": True,
                "windGust": True,
                "windSpeed": True,
                "windChill": True,
            },
            stale=point_cached or grid_cached,
        )
        definitions = {
            "iceAccumulation": (Hazard.WINTER, "ice_accumulation_in", 39.3701),
            "snowfallAmount": (Hazard.WINTER, "snowfall_in", 39.3701),
            "windGust": (Hazard.CONVECTIVE, "wind_gust_mph", 0.621371),
            "windSpeed": (Hazard.CONVECTIVE, "wind_speed_mph", 0.621371),
            "windChill": (Hazard.WINTER, "wind_chill_f", None),
        }
        metrics: list[MetricReading] = []
        properties = grid.get("properties", {})
        for field, (hazard, metric, multiplier) in definitions.items():
            series = properties.get(field, {})
            unit_code = str(series.get("uom", ""))
            for value in series.get("values", [])[:24]:
                number = _to_number(value.get("value"))
                if number is None:
                    continue
                if multiplier:
                    number *= multiplier
                elif metric == "wind_chill_f" and "degC" in unit_code:
                    number = number * 9 / 5 + 32
                start, end = _valid_time(value.get("validTime", ""), fetched)
                unit = {
                    "ice_accumulation_in": "in",
                    "snowfall_in": "in",
                    "wind_gust_mph": "mph",
                    "wind_speed_mph": "mph",
                    "wind_chill_f": "degF",
                }[metric]
                metrics.append(
                    MetricReading(
                        evidence_id=item.id,
                        hazard=hazard,
                        metric=metric,
                        value=round(number, 2),
                        unit=unit,
                        start=start,
                        end=end,
                    )
                )
        return [item], metrics

    async def national_alerts(self, limit: int = 100) -> dict:
        payload, _ = await self.http.get_json(f"{self.base_url}/alerts/active?status=actual")
        payload["features"] = payload.get("features", [])[:limit]
        return payload
