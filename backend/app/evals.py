from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.app.engine import ThresholdRegistry, evaluate
from backend.app.models import (
    AlertSignal,
    EvidenceBundle,
    EvidenceItem,
    GaugeSignal,
    Hazard,
    MetricReading,
    Recommendation,
)
from backend.app.sample_data import FACILITIES

ROOT = Path(__file__).resolve().parents[2]
EVAL_TIME = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)


def load_scenarios(path: Path = ROOT / "evals" / "scenarios.json") -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_scenario(scenario: dict[str, Any]) -> Recommendation:
    facility = FACILITIES[0]
    digest = hashlib.sha256(json.dumps(scenario, sort_keys=True).encode()).hexdigest()
    item = EvidenceItem(
        id=f"eval-{scenario['id']}",
        source="Recorded eval scenario",
        url=f"fixture://evals/{scenario['id']}",
        issued_at=EVAL_TIME,
        fetched_at=EVAL_TIME,
        sha256=digest,
        object_key=f"evals/{digest}.json",
        fields_used={"scenario": scenario["id"]},
    )
    alerts = [
        AlertSignal(
            evidence_id=item.id,
            event=alert["event"],
            severity=alert.get("severity", "Unknown"),
            certainty="Likely",
            urgency="Expected",
            onset=EVAL_TIME + timedelta(hours=alert["onset_h"]),
            ends=EVAL_TIME + timedelta(hours=alert["onset_h"] + alert["duration_h"]),
            covers_facility=True,
        )
        for alert in scenario.get("alerts", [])
    ]
    metrics = [
        MetricReading(
            evidence_id=item.id,
            hazard=Hazard(metric["hazard"]),
            metric=metric["metric"],
            value=metric["value"],
            unit=metric["unit"],
            start=EVAL_TIME + timedelta(hours=metric["onset_h"]),
            end=EVAL_TIME + timedelta(hours=metric["onset_h"] + metric["duration_h"]),
        )
        for metric in scenario.get("metrics", [])
    ]
    gauges = []
    if category := scenario.get("gauge_category"):
        gauges.append(
            GaugeSignal(
                evidence_id=item.id,
                gauge_id="EVAL1",
                observed_at=EVAL_TIME,
                stage=12.0,
                category=category,
            )
        )
    evidence = EvidenceBundle(
        facility_id=facility.id,
        as_of=EVAL_TIME,
        items=[item],
        alerts=alerts,
        metrics=metrics,
        gauges=gauges,
        mode="replay",
        notices=["Recorded evaluation scenario; not live evidence."],
    )
    return evaluate(facility, evidence, EVAL_TIME, ThresholdRegistry.load())


def run_eval_set() -> list[dict[str, Any]]:
    results = []
    for scenario in load_scenarios():
        recommendation = evaluate_scenario(scenario)
        passed = (
            recommendation.posture.value == scenario["expected_posture"]
            and recommendation.shelter_now == scenario.get("expected_shelter", False)
            and recommendation.rationale_grounded
            and bool(recommendation.inputs)
        )
        results.append(
            {
                "id": scenario["id"],
                "expected": scenario["expected_posture"],
                "actual": recommendation.posture.value,
                "shelter_now": recommendation.shelter_now,
                "passed": passed,
            }
        )
    return results
