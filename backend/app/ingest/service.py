from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast

from backend.app.models import (
    AlertSignal,
    EvidenceBundle,
    EvidenceItem,
    Facility,
    GaugeSignal,
    MetricReading,
)

from .nwps import NWPSClient
from .nws import NWSClient


class IngestService:
    def __init__(self, nws: NWSClient, nwps: NWPSClient) -> None:
        self.nws = nws
        self.nwps = nwps

    async def collect(self, facility: Facility) -> EvidenceBundle:
        results = await asyncio.gather(
            self.nws.active_alerts(facility),
            self.nws.gridpoint(facility),
            self.nwps.gauge(facility),
            return_exceptions=True,
        )
        items: list[EvidenceItem] = []
        alerts: list[AlertSignal] = []
        metrics: list[MetricReading] = []
        gauges: list[GaugeSignal] = []
        notices: list[str] = []
        alert_result, grid_result, gauge_result = results
        if isinstance(alert_result, BaseException):
            notices.append(f"NWS alerts unavailable: {alert_result}")
        else:
            alert_items, alert_values = cast(
                tuple[list[EvidenceItem], list[AlertSignal]], alert_result
            )
            items.extend(alert_items)
            alerts.extend(alert_values)
        if isinstance(grid_result, BaseException):
            notices.append(f"NWS gridpoints unavailable: {grid_result}")
        else:
            grid_items, grid_values = cast(
                tuple[list[EvidenceItem], list[MetricReading]], grid_result
            )
            items.extend(grid_items)
            metrics.extend(grid_values)
        if isinstance(gauge_result, BaseException):
            notices.append(f"NWPS gauge unavailable: {gauge_result}")
        else:
            gauge_items, gauge_values = cast(
                tuple[list[EvidenceItem], list[GaugeSignal]], gauge_result
            )
            items.extend(gauge_items)
            gauges.extend(gauge_values)
        mode = "live"
        if any(item.stale for item in items):
            mode = "cached"
            notices.append("One or more sources were served from cache; confidence is reduced.")
        if not items:
            raise RuntimeError("No live or cached evidence sources were available")
        return EvidenceBundle(
            facility_id=facility.id,
            as_of=datetime.now(UTC),
            items=items,
            alerts=alerts,
            metrics=metrics,
            gauges=gauges,
            mode=mode,
            notices=notices,
        )
