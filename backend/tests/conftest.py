from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.models import (
    AlertSignal,
    EvidenceBundle,
    EvidenceItem,
    Facility,
    Hazard,
    MetricReading,
)
from backend.app.sample_data import FACILITIES


@pytest.fixture
def facility() -> Facility:
    return FACILITIES[0]


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 1, 15, 10, 0, tzinfo=UTC)


def make_bundle(
    facility: Facility,
    now: datetime,
    *,
    ice: float = 0.0,
    event: str = "Winter Weather Advisory",
    onset_hours: float = 3.0,
    duration_hours: float = 4.0,
) -> EvidenceBundle:
    digest = hashlib.sha256(f"{facility.id}:{now}:{ice}:{event}".encode()).hexdigest()
    item = EvidenceItem(
        id="evidence-1",
        source="NWS recorded fixture",
        url="https://api.weather.gov/example",
        issued_at=now - timedelta(minutes=5),
        fetched_at=now,
        sha256=digest,
        object_key=f"tests/{digest}.json",
        fields_used={"iceAccumulation": ice, "event": event},
    )
    onset = now + timedelta(hours=onset_hours)
    end = onset + timedelta(hours=duration_hours)
    metrics = []
    if ice:
        metrics.append(
            MetricReading(
                evidence_id=item.id,
                hazard=Hazard.WINTER,
                metric="ice_accumulation_in",
                value=ice,
                unit="in",
                start=onset,
                end=end,
            )
        )
    return EvidenceBundle(
        facility_id=facility.id,
        as_of=now,
        items=[item],
        alerts=[
            AlertSignal(
                evidence_id=item.id,
                event=event,
                severity="Severe" if "Warning" in event else "Moderate",
                certainty="Likely",
                urgency="Expected",
                onset=onset,
                ends=end,
                covers_facility=True,
            )
        ],
        metrics=metrics,
        mode="live",
    )


@pytest.fixture
def bundle_factory():
    return make_bundle
