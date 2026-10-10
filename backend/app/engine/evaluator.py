from __future__ import annotations

import math
import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from backend.app.engine.registry import ThresholdRegistry
from backend.app.models import (
    AlertSignal,
    Confidence,
    ConfidenceLevel,
    Counterfactual,
    EvidenceBundle,
    Facility,
    Hazard,
    MetricReading,
    Posture,
    Recommendation,
    RecommendationInput,
    ThresholdCrossing,
)

ALERT_LEVELS = {
    "warning": 3,
    "emergency": 4,
    "watch": 2,
    "advisory": 2,
    "statement": 1,
    "outlook": 1,
}
LIFE_SAFETY_EVENTS = {"tornado warning", "flash flood emergency", "extreme wind warning"}


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _alert_level(alert: AlertSignal) -> int:
    name = alert.event.lower()
    if "emergency" in name:
        return 4
    for label, level in ALERT_LEVELS.items():
        if label in name:
            return level
    return {"Extreme": 4, "Severe": 3, "Moderate": 2, "Minor": 1}.get(alert.severity, 1)


def _threshold_crossing(
    reading: MetricReading, registry: ThresholdRegistry
) -> tuple[int, list[ThresholdCrossing]]:
    level = 0
    crossings: list[ThresholdCrossing] = []
    for threshold in registry.for_metric(reading.metric):
        limit = float(threshold.value)
        if reading.value < limit:
            continue
        level = max(level, threshold.level)
        crossings.append(
            ThresholdCrossing(
                id=threshold.id,
                hazard=threshold.hazard,
                observed=reading.value,
                limit=limit,
                margin=f"+{reading.value - limit:.2f} {threshold.unit}",
                level=threshold.level,
                posture_floor=threshold.posture_floor,
                rationale_ref=f"THRESHOLDS.md#{threshold.id}",
                evidence_id=reading.evidence_id,
            )
        )
    return level, crossings


def _windows(
    facility: Facility, now: datetime
) -> tuple[datetime, datetime, datetime, datetime, datetime]:
    local_now = _utc(now).astimezone(ZoneInfo(facility.tz))
    day = local_now.date()
    open_local = datetime.combine(day, facility.opens_at, ZoneInfo(facility.tz))
    close_local = datetime.combine(day, facility.closes_at, ZoneInfo(facility.tz))
    if local_now > close_local + timedelta(hours=2):
        open_local += timedelta(days=1)
        close_local += timedelta(days=1)
    arrival_start = open_local - timedelta(hours=2)
    arrival_end = open_local + timedelta(minutes=30)
    departure_start = close_local - timedelta(hours=2)
    departure_end = close_local + timedelta(minutes=90)
    return (
        arrival_start.astimezone(UTC),
        arrival_end.astimezone(UTC),
        departure_start.astimezone(UTC),
        departure_end.astimezone(UTC),
        open_local.astimezone(UTC),
    )


def _overlaps(start: datetime, end: datetime, left: datetime, right: datetime) -> bool:
    return _utc(start) < right and _utc(end) >= left


def _build_timeline(
    evidence: EvidenceBundle,
    now: datetime,
    registry: ThresholdRegistry,
) -> tuple[list[dict[str, object]], list[ThresholdCrossing]]:
    now = _utc(now).replace(minute=0, second=0, microsecond=0)
    levels: dict[datetime, dict[Hazard, int]] = {
        now + timedelta(hours=offset): defaultdict(int) for offset in range(25)
    }
    crossings_by_key: dict[tuple[str, str], ThresholdCrossing] = {}
    for alert in evidence.alerts:
        if not alert.covers_facility:
            continue
        hazard = _hazard_for_event(alert.event)
        level = _alert_level(alert)
        for hour in levels:
            if _overlaps(alert.onset, alert.ends, hour, hour + timedelta(hours=1)):
                levels[hour][hazard] = max(levels[hour][hazard], level)
    for reading in evidence.metrics:
        level, crossings = _threshold_crossing(reading, registry)
        for crossing in crossings:
            crossings_by_key[(crossing.id, crossing.evidence_id)] = crossing
        for hour in levels:
            if _overlaps(reading.start, reading.end, hour, hour + timedelta(hours=1)):
                levels[hour][reading.hazard] = max(levels[hour][reading.hazard], level)
    gauge_levels = {"none": 0, "unknown": 0, "action": 1, "minor": 2, "moderate": 3, "major": 4}
    for gauge in evidence.gauges:
        level = gauge_levels[gauge.category]
        if level:
            for hour in levels:
                levels[hour][Hazard.FLOOD] = max(levels[hour][Hazard.FLOOD], level)
            crossings_by_key[(f"flood_{gauge.category}", gauge.evidence_id)] = ThresholdCrossing(
                id=f"flood_{gauge.category}",
                hazard=Hazard.FLOOD,
                observed=gauge.stage if gauge.stage is not None else gauge.category,
                limit=gauge.thresholds.get(gauge.category, gauge.category),
                margin=f"category: {gauge.category}",
                level=level,
                posture_floor=Posture.CLOSED if level == 4 else None,
                rationale_ref="THRESHOLDS.md#flood-stage",
                evidence_id=gauge.evidence_id,
            )
    timeline = [
        {
            "at": hour.isoformat(),
            "level": max(by_hazard.values(), default=0),
            "hazards": {hazard.value: level for hazard, level in by_hazard.items()},
        }
        for hour, by_hazard in levels.items()
    ]
    return timeline, list(crossings_by_key.values())


def _hazard_for_event(event: str) -> Hazard:
    lowered = event.lower()
    if any(word in lowered for word in ("snow", "ice", "winter", "blizzard", "cold", "freeze")):
        return Hazard.WINTER
    if any(word in lowered for word in ("flood", "surge", "hydrologic")):
        return Hazard.FLOOD
    if any(word in lowered for word in ("tornado", "thunderstorm", "wind", "convective")):
        return Hazard.CONVECTIVE
    return Hazard.OTHER


def _max_in_window(timeline: list[dict[str, object]], start: datetime, end: datetime) -> int:
    return max(
        (
            cast(int, row["level"])
            for row in timeline
            if start <= datetime.fromisoformat(str(row["at"])) <= end
        ),
        default=0,
    )


def _confidence(evidence: EvidenceBundle, now: datetime) -> Confidence:
    certainty_values = [alert.certainty for alert in evidence.alerts]
    certainty = certainty_values[0] if certainty_values else "Unknown"
    onset_hours = [
        (_utc(alert.onset) - _utc(now)).total_seconds() / 3600 for alert in evidence.alerts
    ]
    lead_time = round(min(onset_hours), 1) if onset_hours else "n/a"
    fresh = [
        (_utc(now) - _utc(item.fetched_at)).total_seconds() / 60 <= 30 for item in evidence.items
    ]
    stale_count = sum(not value for value in fresh) + sum(item.stale for item in evidence.items)
    sources = {item.source.split()[0] for item in evidence.items if not item.error}
    alert_hazards = {_hazard_for_event(alert.event) for alert in evidence.alerts}
    metric_hazards = {metric.hazard for metric in evidence.metrics}
    corroborated = bool(alert_hazards & metric_hazards) or bool(
        evidence.gauges and Hazard.FLOOD in alert_hazards
    )
    if not evidence.items or stale_count or evidence.mode in {"cached", "replay", "synthetic"}:
        level = ConfidenceLevel.LOW
    elif certainty in {"Observed", "Likely"} and (corroborated or len(sources) >= 2):
        level = ConfidenceLevel.HIGH
    else:
        level = ConfidenceLevel.MEDIUM
    return Confidence(
        level=level,
        components={
            "alert_certainty": certainty,
            "lead_time_h": lead_time,
            "source_agreement": "corroborated" if corroborated else "single signal",
            "freshness": "STALE" if stale_count else "OK",
            "data_mode": evidence.mode,
        },
    )


def _counterfactuals(
    posture: Posture,
    crossings: list[ThresholdCrossing],
    timeline: list[dict[str, object]],
) -> list[Counterfactual]:
    results: list[Counterfactual] = []
    strongest = max(crossings, key=lambda item: item.level, default=None)
    if strongest and isinstance(strongest.limit, (int, float)):
        lower = Posture.TELEWORK_OPTION if strongest.level >= 3 else Posture.NORMAL
        results.append(
            Counterfactual(
                **{
                    "if": f"{strongest.id} falls below {strongest.limit} {strongest.margin.split()[-1]}",
                    "then": lower,
                    "direction": "lower",
                    "delta": f"decrease by {strongest.margin}",
                }
            )
        )
    max_level = max((cast(int, row["level"]) for row in timeline), default=0)
    if posture != Posture.CLOSED:
        results.append(
            Counterfactual(
                **{
                    "if": "a level 4 hazard enters the workday",
                    "then": Posture.CLOSED,
                    "direction": "higher",
                    "delta": f"severity from {max_level} to 4",
                }
            )
        )
    if posture == Posture.NORMAL:
        results.insert(
            0,
            Counterfactual(
                **{
                    "if": "a level 2 hazard enters an arrival or departure window",
                    "then": Posture.TELEWORK_OPTION,
                    "direction": "higher",
                    "delta": "window severity to 2",
                }
            ),
        )
    return results[:3]


def _rationale(
    facility: Facility,
    posture: Posture,
    arrival_level: int,
    departure_level: int,
    workday_level: int,
    confidence: Confidence,
    crossings: list[ThresholdCrossing],
) -> str:
    details = (
        f" The strongest quantitative trigger is {crossings[-1].id} at "
        f"{crossings[-1].observed} against {crossings[-1].limit}."
        if crossings
        else " No quantitative registry threshold is crossed."
    )
    return (
        f"FirstLight recommends {posture.value.replace('_', ' ').lower()} for {facility.name} in "
        f"{facility.city}. Arrival, departure, and workday severity levels are {arrival_level}, "
        f"{departure_level}, and {workday_level}, respectively.{details} Confidence is "
        f"{confidence.level.value.lower()}; a manager must approve or change this recommendation "
        "before any employee notification is released."
    )


def evaluate(
    facility: Facility,
    evidence: EvidenceBundle,
    now: datetime,
    registry: ThresholdRegistry,
) -> Recommendation:
    """Pure decision function. It performs no I/O and never calls an LLM."""
    now = _utc(now)
    timeline, crossings = _build_timeline(evidence, now, registry)
    arrival_start, arrival_end, departure_start, departure_end, open_at = _windows(facility, now)
    arrival_level = _max_in_window(timeline, arrival_start, arrival_end)
    departure_level = _max_in_window(timeline, departure_start, departure_end)
    workday_end = open_at + (
        datetime.combine(now.date(), facility.closes_at)
        - datetime.combine(now.date(), facility.opens_at)
    )
    workday_level = _max_in_window(timeline, open_at, workday_end)
    midday = open_at + timedelta(hours=4)
    midday_level = _max_in_window(timeline, open_at, midday)
    late_level = _max_in_window(timeline, midday, workday_end)
    max_window = max(arrival_level, departure_level)

    if workday_level >= 4 or (arrival_level >= 3 and late_level >= 3):
        posture = Posture.CLOSED
    elif arrival_level >= 3:
        posture = Posture.DELAYED_ARRIVAL
    elif departure_level >= 3 or (midday_level < 3 and late_level >= 3):
        posture = Posture.EARLY_DISMISSAL
    elif max_window == 2:
        posture = Posture.TELEWORK_OPTION
    else:
        posture = Posture.NORMAL

    posture_floors = [crossing.posture_floor for crossing in crossings if crossing.posture_floor]
    if Posture.CLOSED in posture_floors:
        posture = Posture.CLOSED

    severe_hours = [
        datetime.fromisoformat(str(row["at"])) for row in timeline if cast(int, row["level"]) >= 3
    ]
    clear_at = max(severe_hours, default=open_at) + timedelta(hours=1)
    delay_hours = None
    depart_by = None
    if posture == Posture.DELAYED_ARRIVAL:
        delay_hours = min(4, max(1, math.ceil((clear_at - open_at).total_seconds() / 3600)))
    if posture == Posture.EARLY_DISMISSAL:
        first_severe = min(severe_hours, default=departure_start)
        depart_by = first_severe - timedelta(minutes=75)

    shelter_now = any(
        alert.event.lower() in LIFE_SAFETY_EVENTS
        and alert.covers_facility
        and _utc(alert.onset) <= now <= _utc(alert.ends)
        for alert in evidence.alerts
    )
    confidence = _confidence(evidence, now)
    deadline = max(now, open_at - timedelta(hours=2, minutes=40))
    engine_version = os.getenv("GIT_SHA", "dev")
    rationale = _rationale(
        facility, posture, arrival_level, departure_level, workday_level, confidence, crossings
    )
    return Recommendation(
        facility_id=facility.id,
        as_of=evidence.as_of,
        engine_version=f"git:{engine_version}",
        registry_version=registry.version,
        posture=posture,
        delay_hours=delay_hours,
        depart_by=depart_by,
        shelter_now=shelter_now,
        decision_deadline=deadline,
        inputs=[RecommendationInput.model_validate(item.model_dump()) for item in evidence.items],
        thresholds_crossed=sorted(crossings, key=lambda item: (item.level, item.id)),
        confidence=confidence,
        what_would_change=_counterfactuals(posture, crossings, timeline),
        rationale_template=rationale,
        rationale_grounded=True,
        severity_timeline=timeline,
        data_mode=evidence.mode,
        notices=evidence.notices,
    )
