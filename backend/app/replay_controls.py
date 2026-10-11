"""A retained observational negative control, independent of storm/closure labels.

The source rows are unchanged METAR records from the checksummed repository dataset.
Only observations available by the selected time enter the rules; full-day outcomes
are separate hindsight evidence. Forecasts and warnings are explicitly unavailable.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from adapters.base import SourceStatus, utc
from app import historical, snapshots
from app.facility import load_facility
from engine.evaluate import assess, json_ready

CONTROL_ID = "normal-2024-07-18"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/history/normal-2024-07-18.json"


@lru_cache(maxsize=1)
def fixture() -> dict:
    data = json.loads(FIXTURE.read_text())
    digest = hashlib.sha256(json.dumps(data["source"]["rows"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != data["source"]["rows_sha256"]:
        raise ValueError("Normal-weather control source checksum mismatch")
    return data


def evaluation(as_of: datetime):
    as_of = utc(as_of)
    facility = load_facility()
    day = fixture()["event"]["impact_day"]
    if as_of.astimezone(ZoneInfo(facility.timezone)).date().isoformat() != day or as_of.second or as_of.microsecond:
        raise HTTPException(422, "Choose a minute on July 18, 2024 in America/Chicago for this control; use date search for other days.")
    raw = fixture()["source"]
    inputs = historical.observation_inputs(raw["rows"], as_of, raw)
    statuses = [
        SourceStatus(adapter="iem_obs", label="AMW archived observations", status="ok", n_inputs=len(inputs),
                     source_time=max(i.source_time for i in inputs if i.source_time), urls=[raw["url"]]),
        SourceStatus(adapter="iem_mos", label="Archived NBS forecast", status="unavailable",
                     detail="Not supplied by this observation-only control."),
        SourceStatus(adapter="iem_vtec", label="Historical warnings", status="unavailable",
                     detail="Original warning/update history is not supplied by this control."),
    ]
    return facility, inputs, statuses, assess(inputs, statuses, facility, as_of, "backtest", employees=[])


def event() -> dict:
    data = fixture()
    spec = data["event"]
    facility = load_facility()
    start, end = datetime.fromisoformat(spec["start"]), datetime.fromisoformat(spec["end"])
    timeline = []
    t = start
    while t <= end:
        _, _, _, result = evaluation(t)
        timeline.append({"as_of": t.isoformat(), "posture": result.posture.posture,
                         "readiness": result.readiness.level, "confidence": result.confidence.level,
                         "coverage": "partial", "unavailable_sources": ["Archived forecast", "Historical warnings"]})
        t += timedelta(hours=1)
    four = historical.local_instant(spec["impact_day"])
    selected = next(p for p in timeline if p["as_of"] == four.isoformat())
    observed = historical.outcome(data["source"]["rows"], spec["impact_day"], facility.timezone)
    if not observed["gradable"] or observed["disruptive"] or observed["hours"] != observed["expected_hours"]:
        raise ValueError("Normal-weather control requires complete, independently quiet station observations")
    return {**spec, "timeline": timeline,
            "verification": {"ok": True, "checks": [{"product": "METAR coverage", "ugc": "AMW", "verified": True,
                            "source_url": data["source"]["url"], "events": [{"link": data["source"]["url"]}]}]},
            "outcome": {**observed, "summary": "24/24 hours covered at AMW; no reported freezing precipitation or snow; no defined station-level disruption.",
                        "amw_obs_note": "Observed outcome only. Historical forecasts, warnings, road conditions and office operating decisions are unknown."},
            "backtest": {"at_0400_local": selected,
                         "verdict": "Observational control: compare the recommendation with the quiet station outcome; future conditions were unknown at 04:00.",
                         "label": "observations only; not a verified office decision"}}


def replay(as_of: datetime) -> dict:
    facility, inputs, statuses, result = evaluation(as_of)
    snap = snapshots.build_snapshot_dict(facility, result, inputs, statuses, "backtest", CONTROL_ID)
    from ai.fallback import build
    from ai.prompts import PROMPT_VERSION
    snap["ai"] = build(snap, []).model_dump(mode="json")
    snap["model_id"], snap["prompt_version"] = "deterministic-fallback", PROMPT_VERSION
    # A deterministic id permits reuse without changing previously recorded snapshots.
    snap["snapshot_id"] = "control-" + snapshots.content_hash(snap)[:32]
    saved = snapshots.get(snap["snapshot_id"])
    snap = saved or snapshots.store(snap)
    observed = historical.outcome(fixture()["source"]["rows"], fixture()["event"]["impact_day"], facility.timezone)
    snap["historical_context"] = json_ready({
        "id": snap["snapshot_id"], "day": fixture()["event"]["impact_day"], "as_of": snap["as_of"],
        "status": "partial", "reconstruction": "Retained observation-only normal-weather control",
        "detail": "Quiet local weather is verified by a complete daily station record. Forecast and warning evidence remain unknown at the selected time.",
        "outcome": observed, "missing": [s.detail for s in statuses if s.status == "unavailable"],
        "assumptions": ["Only observations at least 15 minutes before evaluation enter the rules.",
                        "One illustrative day is not a false-alarm rate or proof the facility stayed open."],
        "source_coverage": [s.model_dump(mode="json") for s in statuses],
        "provenance": {k: v for k, v in fixture()["source"].items() if k != "rows"},
        "proxy_records": [], "control": {"kind": "normal-weather", "event_id": CONTROL_ID},
    })
    return snap
