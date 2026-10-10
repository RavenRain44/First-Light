from __future__ import annotations

import hashlib
import random
from datetime import UTC, datetime, time, timedelta

from backend.app.models import (
    AlertSignal,
    Contact,
    Employee,
    EmployeeStatus,
    EvidenceBundle,
    EvidenceItem,
    Facility,
    GaugeSignal,
    Hazard,
    MetricReading,
)

FACILITIES = [
    Facility(
        id="ia-des-moines",
        name="USDA Service Center",
        city="Des Moines",
        state="IA",
        lat=41.5868,
        lon=-93.625,
        tz="America/Chicago",
        ugc_zones=["IAZ060", "IAC153"],
        nearest_gauge="DESI4",
        flood_exposure=0.6,
        region="Midwest",
    ),
    Facility(
        id="la-baton-rouge",
        name="USDA Service Center",
        city="Baton Rouge",
        state="LA",
        lat=30.4515,
        lon=-91.1871,
        tz="America/Chicago",
        ugc_zones=["LAZ048", "LAC033"],
        nearest_gauge="BTRL1",
        flood_exposure=1.4,
        region="Gulf Coast",
    ),
    Facility(
        id="ms-greenville",
        name="USDA Service Center",
        city="Greenville",
        state="MS",
        lat=33.4101,
        lon=-91.0618,
        tz="America/Chicago",
        ugc_zones=["MSZ034", "MSC151"],
        nearest_gauge="GEEM6",
        flood_exposure=1.7,
        region="Mississippi Delta",
    ),
    Facility(
        id="ks-dodge-city",
        name="USDA Service Center",
        city="Dodge City",
        state="KS",
        lat=37.7528,
        lon=-100.0171,
        tz="America/Chicago",
        ugc_zones=["KSZ075", "KSC057"],
        nearest_gauge="DDCK1",
        flood_exposure=0.5,
        region="Plains",
    ),
    Facility(
        id="co-denver",
        name="USDA Service Center",
        city="Denver",
        state="CO",
        lat=39.7392,
        lon=-104.9903,
        tz="America/Denver",
        ugc_zones=["COZ040", "COC031"],
        nearest_gauge="DENCO",
        flood_exposure=0.4,
        region="Mountain West",
    ),
    Facility(
        id="az-tucson",
        name="USDA Service Center",
        city="Tucson",
        state="AZ",
        lat=32.2226,
        lon=-110.9747,
        tz="America/Phoenix",
        ugc_zones=["AZZ504", "AZC019"],
        nearest_gauge="TCSA3",
        flood_exposure=0.9,
        region="Southwest",
    ),
]

FIRST_NAMES = [
    "Avery",
    "Jordan",
    "Morgan",
    "Riley",
    "Taylor",
    "Casey",
    "Quinn",
    "Skyler",
    "Cameron",
    "Drew",
    "Reese",
    "Parker",
]
LAST_NAMES = [
    "Brooks",
    "Chen",
    "Diaz",
    "Ellis",
    "Foster",
    "Garcia",
    "Hayes",
    "Ibrahim",
    "Jones",
    "Kim",
    "Lopez",
    "Miller",
]
ROLES = [
    "FSA program analyst",
    "NRCS conservationist",
    "RD loan specialist",
    "administrative officer",
    "field technician",
]


def seeded_employees(
    facilities: list[Facility] = FACILITIES, per_facility: int = 10
) -> list[Employee]:
    rng = random.Random(20261010)
    employees: list[Employee] = []
    for facility_index, facility in enumerate(facilities):
        for index in range(per_facility):
            number = facility_index * per_facility + index
            status = EmployeeStatus.ON_SITE
            detail_facility_id = None
            if number == 4:
                status = EmployeeStatus.LEAVE
            elif number == 5:
                status = EmployeeStatus.TELEWORK
            elif number == 6:
                status = EmployeeStatus.ON_DETAIL
                detail_facility_id = facilities[1].id
            needs: list[str] = []
            channels = ["sms", "email", "voice"]
            if number == 7:
                needs = ["hearing"]
                channels = ["sms", "email"]
            if number == 8:
                needs = ["mobility", "evacuation_assistance"]
            suffix = 100 + number
            employees.append(
                Employee(
                    id=f"emp-{number + 1:03d}",
                    name=f"{FIRST_NAMES[number % len(FIRST_NAMES)]} {LAST_NAMES[(number * 5) % len(LAST_NAMES)]}",
                    role=ROLES[number % len(ROLES)],
                    home_facility_id=facility.id,
                    status_today=status,
                    detail_facility_id=detail_facility_id,
                    essential=index == 0 and facility_index < 3,
                    telework_eligible=index % 3 != 0,
                    telework_agreement_signed=index % 3 != 0,
                    accessibility_needs=needs,
                    shift_start=time(7 + index % 3, 30 if index % 2 else 0),
                    commute_minutes=rng.randint(15, 65),
                    commute_origin_zone=facility.ugc_zones[0]
                    if index != 9
                    else f"{facility.state}Z999",
                    preferred_channels=channels,
                    language="es" if number == 9 else "en",
                    supervisor_id=f"emp-{facility_index * per_facility + 1:03d}" if index else None,
                    contact=Contact(
                        email=f"employee{number + 1}@example.invalid",
                        sms=f"+155501{suffix:04d}"[-12:],
                        voice=f"+155501{suffix:04d}"[-12:] if "hearing" not in needs else None,
                    ),
                )
            )
    return employees


def _evidence_item(
    identifier: str, source: str, url: str, issued: datetime, fields: dict
) -> EvidenceItem:
    digest = hashlib.sha256(f"{identifier}:{issued.isoformat()}".encode()).hexdigest()
    return EvidenceItem(
        id=identifier,
        source=source,
        url=url,
        issued_at=issued,
        fetched_at=issued + timedelta(minutes=2),
        sha256=digest,
        object_key=f"demo/{digest}.json",
        fields_used=fields,
    )


def demo_evidence(facility: Facility, now: datetime | None = None) -> EvidenceBundle:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    issued = now - timedelta(minutes=8)
    alert_item = _evidence_item(
        f"demo-alert-{facility.id}",
        "NWS alerts",
        "https://api.weather.gov/alerts/active",
        issued,
        {"event": "Ice Storm Warning", "severity": "Severe", "certainty": "Likely"},
    )
    grid_item = _evidence_item(
        f"demo-grid-{facility.id}",
        "NWS gridpoints",
        "https://api.weather.gov/gridpoints/DMX/73,49",
        issued,
        {"iceAccumulation": 0.31, "windGust": 37},
    )
    gauge_item = _evidence_item(
        f"demo-gauge-{facility.id}",
        "NWPS gauge",
        f"https://api.water.noaa.gov/nwps/v1/gauges/{facility.nearest_gauge}/stageflow",
        issued,
        {"category": "action", "stage": 10.2},
    )
    onset = now + timedelta(minutes=30)
    end = onset + timedelta(hours=7)
    return EvidenceBundle(
        facility_id=facility.id,
        as_of=now,
        items=[alert_item, grid_item, gauge_item],
        alerts=[
            AlertSignal(
                evidence_id=alert_item.id,
                event="Ice Storm Warning",
                severity="Severe",
                certainty="Likely",
                urgency="Expected",
                onset=onset,
                ends=end,
                headline="Significant icing expected during the morning commute",
                area_desc=f"{facility.city} area",
                ugc_zones=facility.ugc_zones,
                covers_facility=True,
            )
        ],
        metrics=[
            MetricReading(
                evidence_id=grid_item.id,
                hazard=Hazard.WINTER,
                metric="ice_accumulation_in",
                value=0.31,
                unit="in",
                start=onset,
                end=end,
            ),
            MetricReading(
                evidence_id=grid_item.id,
                hazard=Hazard.CONVECTIVE,
                metric="wind_gust_mph",
                value=37,
                unit="mph",
                start=onset,
                end=end,
            ),
        ],
        gauges=[
            GaugeSignal(
                evidence_id=gauge_item.id,
                gauge_id=facility.nearest_gauge or "demo",
                observed_at=issued,
                stage=10.2,
                category="action",
                thresholds={"action": 10.0, "minor": 12.0, "moderate": 15.0, "major": 18.0},
            )
        ],
        mode="synthetic",
        notices=[
            "Demo evidence is synthetic and clearly labeled; use Refresh live data for operational inputs."
        ],
    )
