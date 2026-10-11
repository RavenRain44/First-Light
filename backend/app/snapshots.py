"""Create, store and load immutable snapshots (the decision record)."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlmodel import select

from adapters.base import Facility, utc
from app.config import settings
from app.db import session
from app.facility import load_employees, roster_summary
from app.models import Decision, Snapshot
from engine.evaluate import Assessment, assess, gather, json_ready
from engine.scoring import load_thresholds

CONTENT_FIELDS = ("facility", "roster", "as_of", "mode", "inputs", "sources", "signals", "rules", "hazards",
                  "posture", "confidence", "changes", "readiness", "watch_next_6h", "analogs", "features", "ai",
                  "thresholds_version", "thresholds_sha256", "model_id", "prompt_version")


def _dumps(x: Any) -> str:
    return json.dumps(json_ready(x), sort_keys=True, separators=(",", ":"), default=str)


def build_snapshot_dict(facility: Facility, a: Assessment, inputs, statuses, mode: str,
                        event_id: str | None = None) -> dict:
    th = load_thresholds()
    return json_ready({
        "snapshot_id": uuid.uuid4().hex,
        "facility": facility,
        "roster": roster_summary(facility, a.posture.decision_day.isoformat()) if not facility.hypothetical else {"hypothetical": True},
        "as_of": a.as_of,
        "created_at": datetime.now(timezone.utc),
        "mode": mode,
        "event_id": event_id,
        "inputs": inputs,
        "sources": statuses,
        "signals": {k: v.model_dump(mode="json", exclude={"hourly"}) for k, v in a.signals.items()},
        "rules": a.rules,
        "hazards": a.hazards,
        "posture": a.posture,
        "confidence": a.confidence,
        "changes": a.changes,
        "readiness": a.readiness,
        "watch_next_6h": a.watch_next_6h,
        "features": a.features,
        "alerts": a.alerts,
        "analogs": [],
        "thresholds_version": th.version,
        "thresholds_sha256": th.sha256,
    }) | {"as_of": utc(a.as_of).isoformat(), "created_at": datetime.now(timezone.utc).isoformat()}


# Fields added after the first snapshots were written. When absent they are left out of the
# hash, so older records still verify against the hash they were stored with.
LATER_FIELDS = {"readiness"}


def content_hash(snap: dict) -> str:
    payload = {k: snap.get(k) for k in CONTENT_FIELDS if not (k in LATER_FIELDS and not snap.get(k))}
    return hashlib.sha256(_dumps(payload).encode()).hexdigest()


def store(snap: dict) -> dict:
    snap["content_sha256"] = content_hash(snap)
    row = Snapshot(
        snapshot_id=snap["snapshot_id"], facility_id=snap["facility"]["id"],
        as_of=datetime.fromisoformat(snap["as_of"]), created_at=datetime.fromisoformat(snap["created_at"]),
        mode=snap["mode"], event_id=snap.get("event_id"), posture=snap["posture"]["posture"],
        opm_label=snap["posture"]["opm_label"], confidence=snap["confidence"]["level"],
        confidence_score=snap["confidence"]["score"], thresholds_version=snap["thresholds_version"],
        thresholds_sha256=snap["thresholds_sha256"], model_id=snap["model_id"], prompt_version=snap["prompt_version"],
        content_sha256=snap["content_sha256"], facility_json=_dumps(snap["facility"]), roster_json=_dumps(snap["roster"]),
        inputs_json=_dumps(snap["inputs"]), sources_json=_dumps(snap["sources"]), signals_json=_dumps(snap["signals"]),
        rules_json=_dumps(snap["rules"]), hazards_json=_dumps(snap["hazards"]), posture_json=_dumps(snap["posture"]),
        confidence_json=_dumps(snap["confidence"]), changes_json=_dumps(snap["changes"]),
        readiness_level=snap["readiness"]["level"], readiness_json=_dumps(snap["readiness"]),
        watch_json=_dumps(snap["watch_next_6h"]), analogs_json=_dumps(snap["analogs"]),
        features_json=_dumps(snap["features"]), ai_json=_dumps(snap["ai"]),
    )
    with session() as s:
        s.add(row)
        s.commit()
    return snap


def row_to_dict(row: Snapshot, include_inputs: bool = True) -> dict:
    inputs = json.loads(row.inputs_json) if include_inputs else None
    d = {
        "snapshot_id": row.snapshot_id, "facility_id": row.facility_id, "as_of": utc(row.as_of).isoformat(),
        "created_at": utc(row.created_at).isoformat(), "mode": row.mode, "event_id": row.event_id,
        "thresholds_version": row.thresholds_version, "thresholds_sha256": row.thresholds_sha256,
        "model_id": row.model_id, "prompt_version": row.prompt_version, "content_sha256": row.content_sha256,
        "facility": json.loads(row.facility_json), "roster": json.loads(row.roster_json),
        "sources": json.loads(row.sources_json), "signals": json.loads(row.signals_json),
        "rules": json.loads(row.rules_json), "hazards": json.loads(row.hazards_json),
        "posture": json.loads(row.posture_json), "confidence": json.loads(row.confidence_json),
        "changes": json.loads(row.changes_json), "watch_next_6h": json.loads(row.watch_json),
        "readiness": json.loads(row.readiness_json or "{}") or None,
        "analogs": json.loads(row.analogs_json), "features": json.loads(row.features_json),
        "ai": json.loads(row.ai_json),
    }
    if include_inputs:
        d["inputs"] = inputs
        d["alerts"] = [i["data"] for i in inputs if i["kind"] == "alert"]
    d["integrity_ok"] = content_hash(d) == row.content_sha256 if include_inputs else None
    # AI brief added after the snapshot was saved (not part of the snapshot or its hash).
    d["ai_addon"] = interpretation(row.snapshot_id) if include_inputs else None
    return d


def get(snapshot_id: str) -> dict | None:
    with session() as s:
        row = s.get(Snapshot, snapshot_id)
        return row_to_dict(row) if row else None


def latest(facility_id: str, mode: str = "live") -> dict | None:
    with session() as s:
        row = s.exec(select(Snapshot).where(Snapshot.facility_id == facility_id, Snapshot.mode == mode)
                     .order_by(Snapshot.created_at.desc()).limit(1)).first()
        return row_to_dict(row) if row else None


def history(facility_id: str, limit: int = 50, modes: tuple[str, ...] = ("live", "replay")) -> list[dict]:
    with session() as s:
        rows = s.exec(select(Snapshot).where(Snapshot.facility_id == facility_id, Snapshot.mode.in_(modes))
                      .order_by(Snapshot.created_at.desc()).limit(limit)).all()
        decisions = s.exec(select(Decision).where(Decision.facility_id == facility_id)).all()
    by_snap: dict[str, list] = {}
    for d in decisions:
        by_snap.setdefault(d.snapshot_id, []).append(d.model_dump(mode="json"))
    return [{"snapshot_id": r.snapshot_id, "as_of": utc(r.as_of).isoformat(), "created_at": utc(r.created_at).isoformat(),
             "mode": r.mode, "posture": r.posture, "confidence": r.confidence, "model_id": r.model_id,
             "readiness": r.readiness_level or None,
             "decisions": by_snap.get(r.snapshot_id, [])} for r in rows]


async def demo_live_as_of(facility: Facility) -> datetime | None:
    """DEMO_MODE: evaluate "live" at the moment the cached live forecast was fetched, so every
    date-keyed request (e.g. today's observations) matches what is in the cache."""
    from adapters import cache
    from adapters.nws import resolve_point
    try:
        meta, _ = await resolve_point(facility.lat, facility.lon)
    except cache.SourceUnavailable:
        return None
    t = cache.cached_fetched_at(meta["forecastGridData"])
    settings.demo_reference_now = t
    return t


async def evaluate(facility: Facility, as_of: datetime | None, mode: str, *, event_id: str | None = None,
                   use_ai: bool = True, persist: bool = True) -> dict:
    """Full pipeline: fetch -> assess -> analogs -> interpretation -> immutable snapshot."""
    from ai import agent as ai_agent
    from engine import analogs as analog_engine

    if as_of is None and mode == "live" and settings.demo_mode:
        as_of = await demo_live_as_of(facility)
    as_of = utc(as_of or datetime.now(timezone.utc))
    inputs, statuses = await gather(facility, as_of, mode)
    employees = None if facility.hypothetical else load_employees()
    here = [e for e in employees or [] if e["this_week_location"] == facility.id and not e["teleworking_today"]]
    a = assess(inputs, statuses, facility, as_of, mode, employees=here)
    snap = build_snapshot_dict(facility, a, inputs, statuses, mode, event_id)
    if mode != "backtest":
        snap["analogs"] = analog_engine.find_analogs(snap["features"], exclude_event=event_id)
    # The snapshot is saved right away with the deterministic template brief (sub-second). When a model
    # is configured, the AI brief is generated in the background and added as a separate append-only
    # record (SnapshotInterpretation), so the decision record never waits on, or is edited by, the model.
    interp, model_id = await ai_agent.interpret(snap, use_model=False)
    snap["ai"] = interp
    snap["model_id"] = model_id
    from ai.prompts import PROMPT_VERSION
    snap["prompt_version"] = PROMPT_VERSION
    if not persist:
        return snap
    store(snap)
    if use_ai and ai_agent.model_enabled():
        _start_enrichment(snap)
    return get(snap["snapshot_id"])


# ----------------------------------------------------------------------------- background AI briefs

_pending: dict[str, datetime] = {}
_tasks: set = set()


def _start_enrichment(snap: dict) -> None:
    import asyncio

    if snap["snapshot_id"] in _pending:
        return
    _pending[snap["snapshot_id"]] = datetime.now(timezone.utc)
    task = asyncio.get_running_loop().create_task(_enrich(snap))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _enrich(snap: dict) -> None:
    import time

    from ai import agent as ai_agent
    from ai.prompts import PROMPT_VERSION
    from app.models import SnapshotInterpretation

    t0 = time.perf_counter()
    try:
        interp, model_id = await ai_agent.interpret(snap, use_model=True)
        status = "ok" if model_id != ai_agent.FALLBACK_ID else "failed"
    except Exception as e:  # noqa: BLE001 - never let a background task crash the app
        interp, model_id, status = {"error": type(e).__name__}, "none", "failed"
    try:
        body = _dumps(interp)
        with session() as s:
            s.add(SnapshotInterpretation(
                snapshot_id=snap["snapshot_id"], created_at=datetime.now(timezone.utc), status=status,
                model_id=model_id, prompt_version=PROMPT_VERSION, seconds=round(time.perf_counter() - t0, 1),
                ai_json=body, content_sha256=hashlib.sha256(body.encode()).hexdigest()))
            s.commit()
    finally:
        _pending.pop(snap["snapshot_id"], None)


def interpretation(snapshot_id: str) -> dict:
    """Latest AI brief for a snapshot: {'status': pending|ok|failed|none, ...}."""
    from app.models import SnapshotInterpretation

    if snapshot_id in _pending:
        return {"status": "pending", "since": _pending[snapshot_id].isoformat()}
    with session() as s:
        row = s.exec(select(SnapshotInterpretation).where(SnapshotInterpretation.snapshot_id == snapshot_id)
                     .order_by(SnapshotInterpretation.id.desc())).first()
    if row is None:
        return {"status": "none"}
    return {"status": row.status, "model_id": row.model_id, "prompt_version": row.prompt_version,
            "created_at": utc(row.created_at).isoformat(), "seconds": row.seconds,
            "ai": json.loads(row.ai_json), "content_sha256": row.content_sha256}


def ensure_interpretation(snap: dict) -> dict:
    """Start the default brief pipeline when a report is loaded for the first time."""
    from ai import agent as ai_agent

    addon = interpretation(snap["snapshot_id"])
    if addon["status"] == "none" and ai_agent.model_enabled():
        _start_enrichment(snap)
        addon = interpretation(snap["snapshot_id"])
    snap["ai_addon"] = addon
    return snap


def regenerate_interpretation(snapshot_id: str) -> dict | None:
    """Ask the model for a fresh brief on an existing snapshot (same recorded facts). The new brief is
    another append-only add-on; the newest one is shown. Returns None if the snapshot doesn't exist."""
    from ai import agent as ai_agent

    if snapshot_id in _pending:
        return interpretation(snapshot_id)
    snap = get(snapshot_id)
    if snap is None:
        return None
    if not ai_agent.model_enabled():
        return {"status": "unavailable"}
    _start_enrichment(snap)
    return interpretation(snapshot_id)
