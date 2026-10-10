from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dateutil.parser import isoparse

from backend.app.ingest.archive import Archive
from backend.app.ingest.http import CachedHTTPClient
from backend.app.models import EvidenceItem, Facility, GaugeSignal


def _find_first(data: Any, keys: set[str]) -> Any:
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in keys and value not in (None, ""):
                return value
        for value in data.values():
            found = _find_first(value, keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in reversed(data):
            found = _find_first(value, keys)
            if found is not None:
                return found
    return None


class NWPSClient:
    base_url = "https://api.water.noaa.gov/nwps/v1"

    def __init__(self, http: CachedHTTPClient, archive: Archive) -> None:
        self.http = http
        self.archive = archive

    async def gauge(self, facility: Facility) -> tuple[list[EvidenceItem], list[GaugeSignal]]:
        if not facility.nearest_gauge:
            return [], []
        metadata_url = f"{self.base_url}/gauges/{facility.nearest_gauge}"
        stage_url = f"{metadata_url}/stageflow"
        metadata, meta_cached = await self.http.get_json(metadata_url, "application/json")
        stageflow, stage_cached = await self.http.get_json(stage_url, "application/json")
        fetched = datetime.now(UTC)
        payload = {"metadata": metadata, "stageflow": stageflow}
        digest, key = self.archive.put("nwps", payload)
        observed_string = _find_first(
            stageflow, {"validtime", "observationtime", "timestamp", "time"}
        )
        try:
            observed = isoparse(str(observed_string)).astimezone(UTC)
        except (TypeError, ValueError):
            observed = fetched
        category_value = str(
            _find_first(metadata, {"statusobserved", "floodcategory", "category"}) or "unknown"
        ).lower()
        category = next(
            (
                name
                for name in ("major", "moderate", "minor", "action", "none")
                if name in category_value
            ),
            "unknown",
        )
        stage = _find_first(stageflow, {"primary", "stage", "value"})
        try:
            stage_number = float(stage)
        except (TypeError, ValueError):
            stage_number = None
        flood = _find_first(metadata, {"floodcategories"}) or {}
        thresholds: dict[str, float] = {}
        for name in ("action", "minor", "moderate", "major"):
            value = _find_first(flood, {name})
            try:
                thresholds[name] = float(value)
            except (TypeError, ValueError):
                pass
        item = EvidenceItem(
            id=f"nwps-{digest[:12]}",
            source="NWPS gauge",
            url=stage_url,
            issued_at=observed,
            fetched_at=fetched,
            sha256=digest,
            object_key=key,
            fields_used={
                "gauge_id": facility.nearest_gauge,
                "stage": stage_number,
                "category": category,
                "thresholds": thresholds,
            },
            stale=meta_cached or stage_cached,
        )
        return [item], [
            GaugeSignal(
                evidence_id=item.id,
                gauge_id=facility.nearest_gauge,
                observed_at=observed,
                stage=stage_number,
                category=category,
                thresholds=thresholds,
            )
        ]
