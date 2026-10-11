"""Policy proposals, pure-engine validation and atomic, manager-authorized activation."""
from __future__ import annotations

import asyncio
import gzip
import hashlib
from collections import Counter
import json
import math
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import select

from adapters.base import Facility, NormalizedInput, SourceStatus
from app import storage
from app.db import session
from app.feedback import dumps, measures, now, sha, utc
from app.models import HistoricalArtifact, HistoricalEvaluation, PolicyActivation, PolicyEvent, PolicyProposal
from engine.scoring import Rule, Thresholds

JOBS = {}
MIN_VALIDATION = 30
MIN_CLASS = 5


def parameters(th):
    from engine.scoring import load_base_thresholds
    anchors = {r.id:r.value for r in load_base_thresholds().rules}
    result = []
    for r in th.rules:
        if r.basis == "policy" and r.operator in (">", ">=", "<", "<=") and r.value != 0:
            original = anchors.get(r.id, r.value)
            lo, hi = sorted((original * .5, original * 1.5))
            result.append({"path": f"rules.{r.id}.value", "category": "weather", "current": r.value,
                           "min": lo, "max": hi, "unit": r.unit, "anchor": r.anchor})
    for category, path, value, lo, hi, unit in (
        ("timing", "timing.winter_road_recovery_hours", th.timing["winter_road_recovery_hours"], 1, 6, "hours"),
        ("readiness", "readiness.red_within_hours", th.raw["readiness"]["red_within_hours"], .5, 4, "hours"),
        ("readiness", "readiness.near_miss_fraction", th.raw["readiness"]["near_miss_fraction"], .3, .9, "fraction"),
        ("confidence", "confidence.medium_min", th.raw.get("confidence_brackets", {}).get("medium_min", .5), .3, .7, "evidence-quality score"),
        ("confidence", "confidence.high_min", th.raw.get("confidence_brackets", {}).get("high_min", .75), .7, .95, "evidence-quality score"),
    ):
        result.append({"path": path, "category": category, "current": value, "min": lo, "max": hi, "unit": unit})
    return result


def validate_changes(th, category, changes):
    allowed = {r["path"]: r for r in parameters(th) if r["category"] == category}
    if not 1 <= len(changes) <= 3 or len({c["path"] for c in changes}) != len(changes):
        raise HTTPException(422, "Choose one to three distinct policy parameters")
    for c in changes:
        p = allowed.get(c["path"])
        v = c["value"]
        if not p or isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not p["min"] <= v <= p["max"]:
            raise HTTPException(422, "Invalid, unbounded or official parameter change")
        if c["path"] == "timing.winter_road_recovery_hours" and v != int(v):
            raise HTTPException(422, "Road recovery hours must be a whole number")
        if v == p["current"]:
            raise HTTPException(422, "Proposed value must differ from the incumbent")
    if category == "confidence":
        values = {r["path"]: r["current"] for r in allowed.values()}
        values.update({r["path"]: r["value"] for r in changes})
        if values["confidence.medium_min"] >= values["confidence.high_min"]:
            raise HTTPException(422, "Confidence brackets must remain ordered")


def candidate(th, category, changes, version):
    validate_changes(th, category, changes)
    raw = deepcopy(th.raw)
    for c in changes:
        path, value = c["path"], c["value"]
        if path.startswith("rules."):
            rid = path[len("rules."):-len(".value")]
            next(r for r in raw["rules"] if r["id"] == rid)["value"] = value
        elif category == "confidence":
            raw.setdefault("confidence_brackets", {"medium_min": .5, "high_min": .75})[path.split(".")[1]] = value
        else:
            section, name = path.split(".")
            raw[section][name] = value
    raw["version"] = version
    return Thresholds(version=version, sha256=sha(raw), raw=raw, rules=[Rule(**r) for r in raw["rules"]],
                      postures=raw["postures"], timing=raw["timing"])


def current_activation(s=None):
    if s is not None:
        return s.exec(select(PolicyActivation).order_by(PolicyActivation.id.desc())).first()
    with session() as s:
        return current_activation(s)


def effective(base):
    from app import db
    from app.config import settings
    if db._engine is None and not settings.db_path.exists():
        return base
    active = current_activation()
    if not active or active.source_base_sha != base.sha256:
        return base
    th = Thresholds.model_validate_json(active.policy_json)
    if active.policy_sha == base.sha256 and th.model_dump() == base.model_dump():
        return base
    if th.sha256 != active.policy_sha or sha(th.raw) != active.policy_sha:
        raise RuntimeError("Active policy integrity check failed")
    return th


def event(s, pid, actor, status, payload=None):
    s.add(PolicyEvent(proposal_id=pid, actor=actor, status=status, created_at=now(), payload_json=dumps(payload or {})))


def get(pid, s=None):
    if s is None:
        with session() as ss:
            return get(pid, ss)
    p = s.get(PolicyProposal, pid)
    if not p:
        raise HTTPException(404, "Policy proposal not found")
    events = s.exec(select(PolicyEvent).where(PolicyEvent.proposal_id == pid).order_by(PolicyEvent.id)).all()
    return {"id": p.id, "created_at": utc(p.created_at).isoformat(), "actor": p.actor, "base_sha": p.base_sha,
            "category": p.category, **json.loads(p.payload_json),
            "status": events[-1].status if events else "proposed", "version": events[-1].id if events else 0,
            "events": [{"id": e.id, "at": utc(e.created_at).isoformat(), "actor": e.actor, "status": e.status,
                        **json.loads(e.payload_json)} for e in events]}


def overview():
    from engine.scoring import load_base_thresholds, load_thresholds
    base, active = load_base_thresholds(), current_activation()
    th = load_thresholds()
    with session() as s:
        ps = s.exec(select(PolicyProposal).order_by(PolicyProposal.created_at.desc()).limit(50)).all()
        proposals = [get(p.id, s) for p in ps]
    from app.config import settings
    return {"parameters": parameters(th), "current_sha": th.sha256, "current_version": th.version,
            "activation": {"id": active.id, "actor": active.actor, "at": utc(active.created_at).isoformat(),
                           "action": active.action, "applicable": active.source_base_sha == base.sha256} if active else None,
            "admin_configured": bool(settings.threshold_admin_token), "proposals": proposals}


def propose(actor, category, changes, rationale, cohort="forecast", c_fp=1., c_fn=5., minimum_recall=None, maximum_false_alarm=None, analysis_id=None):
    from engine.scoring import load_thresholds, load_base_thresholds
    th = load_thresholds()
    validate_changes(th, category, changes)
    pid = uuid4().hex
    th2 = candidate(th, category, changes, "policy-" + pid[:12])
    payload = {"changes": changes, "rationale": rationale, "cohort": cohort, "source_base_sha": load_base_thresholds().sha256,
               "incumbent": th.model_dump(mode="json"), "candidate": th2.model_dump(mode="json"),
               "costs": {"false_alarm": c_fp, "missed_disruption": c_fn, "assumed": True},
               "constraints": {"minimum_recall": minimum_recall, "maximum_false_alarm": maximum_false_alarm},
               "analysis_id": analysis_id, "expected_benefit": "Hypothesis only; full-engine evaluation is required",
               "risks": "Easier cutoffs may increase unnecessary disruption; stricter cutoffs may miss hazardous conditions. Injury and income loss are not measured."}
    with session() as s:
        s.add(PolicyProposal(id=pid, created_at=now(), actor=actor, base_sha=th.sha256, category=category, payload_json=dumps(payload)))
        s.flush(); event(s, pid, actor, "proposed"); s.commit()
    storage.kick()
    return get(pid)


def cohort_rows(kind):
    """Retained artifacts only. No archive downloads, inference or snapshot writes."""
    from app.config import settings
    from app.risk_experiment import manifest_path
    manifest = json.loads(manifest_path().read_text()) if kind == "baseline" and manifest_path().exists() else None
    if kind == "baseline" and not manifest:
        raise ValueError("Frozen 7,470-day manifest is unavailable. Restore the dataset; it is not silently rebuilt.")
    if manifest and (manifest["n"] != 7470 or len(manifest["entries"]) != 7470 or len({r["day"] for r in manifest["entries"]}) != 7470 or sha(manifest["entries"]) != manifest["cohort_sha"]):
        raise ValueError("Frozen baseline identity mismatch")
    with session() as s:
        evaluations = ([s.get(HistoricalEvaluation, r["id"]) for r in manifest["entries"]] if manifest else
                       s.exec(select(HistoricalEvaluation).order_by(HistoricalEvaluation.id)).all())
        pinned = {r["id"]: r for r in manifest["entries"]} if manifest else {}
        unique, excluded = {}, Counter()
        for e in evaluations:
            if not e or not e.artifact_sha:
                if manifest:
                    raise ValueError("Frozen baseline artifact is missing")
                excluded["Missing retained artifact"] += 1; continue
            v = json.loads(e.summary_json)
            if manifest and (e.artifact_sha != pinned[e.id]["artifact_sha"] or hashlib.sha256(e.summary_json.encode()).hexdigest() != pinned[e.id]["summary_sha"]):
                raise ValueError("Frozen evaluation changed")
            if not v.get("outcome", {}).get("gradable") or not v.get("selection_gradable") or v.get("day") != v.get("decision_day", v["day"]):
                excluded["Insufficient outcome/input coverage or wrong decision day"] += 1; continue
            blob = s.get(HistoricalArtifact, e.artifact_sha)
            if not blob or hashlib.sha256(blob.payload).hexdigest() != e.artifact_sha:
                raise ValueError("Retained artifact integrity mismatch")
            snap = json.loads(gzip.decompress(blob.payload))
            at = datetime.fromisoformat(snap["as_of"])
            if at.astimezone(ZoneInfo(snap["facility"]["timezone"])).strftime("%H:%M") != "04:00" or snap["posture"]["decision_day"] != v["day"]:
                excluded["Not the same-day 04:00 decision cutoff"] += 1; continue
            forecast = any(i["role"] == "forecast" and i["kind"] == "series" for i in snap["inputs"])
            if kind == "forecast" and not forecast:
                excluded["No retained pre-decision forecast"] += 1; continue
            if kind == "baseline" and v["requested_mode"] != "observation":
                raise ValueError("Frozen cohort contains a different reconstruction")
            if not safe_inputs(snap):
                excluded["Future or uncertain source issuance in prediction inputs"] += 1; continue
            row = {"day": v["day"], "observed": v["outcome"]["disruptive"], "artifact_sha": e.artifact_sha,
                   "evaluation_id": e.id, "snapshot": snap, "hazard": v.get("hazard", "unknown")}
            unit = (snap["facility"]["id"], v["day"])
            unique.setdefault(unit, row)  # deterministic first retained evaluation; one facility-day
        return sorted(unique.values(), key=lambda r: r["day"]), dict(excluded), manifest



def safe_inputs(snap):
    at = datetime.fromisoformat(snap["as_of"])
    for inp in snap["inputs"]:
        source_time = inp.get("source_time")
        if inp["role"] in ("forecast", "observation", "alert") and (not source_time or datetime.fromisoformat(source_time.replace("Z", "+00:00")) > at):
            return False
        if source_time and inp["role"] in ("forecast", "observation"):
            lag = timedelta(hours=2) if inp["role"] == "forecast" else timedelta(minutes=15)
            if utc(datetime.fromisoformat(source_time.replace("Z", "+00:00"))) + lag > utc(at):
                return False
        if inp["role"] == "observation" and any(utc(datetime.fromisoformat(p["t"].replace("Z", "+00:00"))) > utc(at) - timedelta(minutes=15) for p in inp.get("series") or []):
            return False
        if inp["role"] == "forecast" and (inp.get("data") or {}).get("live_retrieval_only"):
            return False
    return True


def partitions(rows, kind):
    from app.risk_experiment import partition
    if kind == "baseline":
        return partition(rows)
    # Forecasts start in 2019: reserve 2021-22 for selection, 2023+ for retrospective evaluation.
    boundaries = (date(2021, 1, 1), date(2023, 1, 1))
    drops = {r["day"] for r in rows if any(abs((date.fromisoformat(r["day"]) - b).days) <= 2 for b in boundaries)}
    episodes, run = [], []
    for r in rows:
        if r["observed"]:
            if run and (date.fromisoformat(r["day"]) - date.fromisoformat(run[-1]["day"])).days > 1:
                episodes.append(run); run = []
            run.append(r)
        elif run:
            episodes.append(run); run = []
    episodes.append(run)
    for ep in episodes:
        if ep and any(ep[0]["day"] < b.isoformat() <= ep[-1]["day"] for b in boundaries):
            drops.update(r["day"] for r in ep)
    splits = {"training": [], "validation": [], "test": []}
    for r in rows:
        if r["day"] not in drops:
            splits["training" if r["day"] < "2021-01-01" else "validation" if r["day"] < "2023-01-01" else "test"].append(r)
    return splits, sorted(drops)


def rerun(rows, th):
    from engine.evaluate import assess
    results = []
    for r in rows:
        snap = r["snapshot"]
        result = assess([NormalizedInput.model_validate(x) for x in snap["inputs"]],
                        [SourceStatus.model_validate(x) for x in snap.get("sources", [])],
                        Facility.model_validate(snap["facility"]), datetime.fromisoformat(snap["as_of"]),
                        "backtest", th=th, employees=[], include_counterfactuals=False)
        same_day = result.posture.decision_day.isoformat() == r["day"]
        results.append({"day": r["day"], "hazard": r["hazard"], "observed": r["observed"], "prediction": same_day and result.posture.posture != "NORMAL",
                        "posture": result.posture.posture, "readiness": result.readiness.level,
                        "confidence": result.confidence.level, "decision_day": result.posture.decision_day.isoformat()})
    return results


def evaluate_report(p, rows, excluded, manifest):
    base, cand = Thresholds.model_validate(p["incumbent"]), Thresholds.model_validate(p["candidate"])
    splits, purged = partitions(rows, p["cohort"])
    c_fp, c_fn = p["costs"]["false_alarm"], p["costs"]["missed_disruption"]
    scores, classifications = {}, {}
    for key in ("training", "validation"):
        left, right = rerun(splits[key], base), rerun(splits[key], cand)
        classifications[key] = (left, right)
        scores[key] = {"incumbent": measures(((r["prediction"], r["observed"]) for r in left), c_fp, c_fn),
                       "candidate": measures(((r["prediction"], r["observed"]) for r in right), c_fp, c_fn)}
    val = scores["validation"]
    positives = sum(r["observed"] for r in splits["validation"])
    enough = len(splits["validation"]) >= MIN_VALIDATION and positives >= MIN_CLASS and len(splits["validation"]) - positives >= MIN_CLASS
    reason = None
    if p["category"] in ("readiness", "confidence"):
        reason = "This bracket does not alter operating predictions. Independent attention/deadline or calibration labels are absent; descriptive bracket changes cannot establish improved accuracy."
    elif not enough:
        reason = f"Validation needs at least {MIN_VALIDATION} days and {MIN_CLASS} days of each weather class."
    elif not val["candidate"]["weighted_loss"] < val["incumbent"]["weighted_loss"]:
        reason = "Candidate does not reduce the predeclared weighted validation loss."
    constraints = p["constraints"]
    if enough:
        if constraints["minimum_recall"] is not None and val["candidate"]["recall"] < constraints["minimum_recall"]:
            reason = "Candidate fails minimum validation recall."
        if constraints["maximum_false_alarm"] is not None and val["candidate"]["false_positive_rate"]["rate"] > constraints["maximum_false_alarm"]:
            reason = "Candidate exceeds maximum validation false-alarm rate."
    # Candidate fixed before evaluating test labels; test results never select parameter values.
    for key in (("test",) if reason is None else ()):
        left, right = rerun(splits[key], base), rerun(splits[key], cand)
        classifications[key] = (left, right)
        scores[key] = {"incumbent": measures(((r["prediction"], r["observed"]) for r in left), c_fp, c_fn),
                       "candidate": measures(((r["prediction"], r["observed"]) for r in right), c_fp, c_fn)}
    before, after = val["incumbent"]["confusion"], val["candidate"]["confusion"]
    return {"status": "rejected" if reason else "validated", "reason": reason,
            "method": "Full deterministic engine rerun on identical retained decision-time inputs; no margin-offset shortcut",
            "scores": scores,
            "breakdowns": {key: {dimension: {group: {
                "incumbent": measures(((l["prediction"], l["observed"]) for l, r in zip(*pair) if (l["day"][:4] if dimension == "year" else l["hazard"]) == group), c_fp, c_fn),
                "candidate": measures(((r["prediction"], r["observed"]) for l, r in zip(*pair) if (r["day"][:4] if dimension == "year" else r["hazard"]) == group), c_fp, c_fn)}
                for group in sorted({r["day"][:4] if dimension == "year" else r["hazard"] for r in splits[key]})}
                for dimension in ("year", "hazard")} for key, pair in classifications.items()}, "excluded": excluded, "purged_days": purged,
            "cohort_sha": sha([{k: r[k] for k in ("day", "artifact_sha", "evaluation_id")} for r in rows]),
            "cohort_n": len(rows), "source_dataset": manifest["version"] if manifest else "retained-04:00-forecast-inputs",
            "test_status": "Locked candidate evaluated once; retrospective" if reason is None else "Skipped: candidate failed validation selection",
            "config_hashes": {"incumbent": base.sha256, "candidate": cand.sha256},
            "additional_disruptions_caught": after["true_positive"] - before["true_positive"],
            "additional_false_alarms": after["false_alarm"] - before["false_alarm"],
            "operational_burden": "Additional false alarms represent warning-day burden, not measured office downtime or lost income.",
            "bracket_changes": {key: sum(l[p["category"]] != r[p["category"]] for l, r in zip(*pair))
                                for key, pair in classifications.items()} if p["category"] in ("readiness", "confidence") else None,
            "limitations": ["Historical test dates have been inspected before; retrospective evaluation, not pristine prospective validation.",
                            "Test outcomes never choose or revise this candidate. Activation creates a future unseen monitoring stream.",
                            "Storm episodes crossing split boundaries and nearby dates are purged; remaining storm days are still correlated.",
                            "Missing inputs and official definitions are unchanged. Observation-only baselines cannot prove advance warning.",
                            "Weather labels cannot validate five-posture reporting-time correctness, injury risk or office closure accuracy."]}


async def _run(pid, actor):
    try:
        p = get(pid)
        rows, excluded, manifest = await asyncio.to_thread(cohort_rows, p["cohort"])
        report = await asyncio.to_thread(evaluate_report, p, rows, excluded, manifest)
        with session() as s:
            event(s, pid, actor, report["status"], {"report": report}); s.commit()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        with session() as s:
            event(s, pid, actor, "rejected", {"reason": f"Evaluation unavailable: {type(exc).__name__}", "detail": str(exc) if isinstance(exc, ValueError) else "Retained evidence could not be evaluated."}); s.commit()
    finally:
        JOBS.pop(pid, None); storage.kick()


def start(pid, actor, version):
    with session() as s:
        s.exec(text("BEGIN IMMEDIATE"))
        p = get(pid, s)
        if p["status"] != "proposed":
            return p  # no repeated held-out reruns
        if p["version"] != version:
            raise HTTPException(409, "Proposal changed. Refresh before evaluation.")
        event(s, pid, actor, "evaluating"); s.commit()
    JOBS[pid] = asyncio.create_task(_run(pid, actor)); storage.kick()
    return get(pid)


def approve(pid, actor, version):
    from engine.scoring import load_thresholds
    with session() as s:
        s.exec(text("BEGIN IMMEDIATE"))
        p = get(pid, s)
        if p["version"] != version or p["status"] != "validated":
            raise HTTPException(409, "Only the current validated proposal can be approved")
        if load_thresholds().sha256 != p["base_sha"]:
            raise HTTPException(409, "Incumbent policy changed. Create and evaluate a new proposal.")
        event(s, pid, actor, "approved"); s.commit()
    storage.kick(); return get(pid)


def activate(pid, actor, version):
    from engine.scoring import load_base_thresholds
    base = load_base_thresholds()
    with session() as s:
        s.exec(text("BEGIN IMMEDIATE"))
        p = get(pid, s)
        if p["version"] != version or p["status"] != "approved":
            raise HTTPException(409, "Only the current approved proposal can be activated")
        prior = current_activation(s)
        incumbent_sha = prior.policy_sha if prior and prior.source_base_sha == base.sha256 else base.sha256
        if incumbent_sha != p["base_sha"] or p["source_base_sha"] != base.sha256:
            raise HTTPException(409, "Policy changed after evaluation. Re-evaluate a new proposal.")
        s.add(PolicyActivation(proposal_id=pid, created_at=now(), actor=actor, action="activate", source_base_sha=base.sha256,
                               policy_sha=p["candidate"]["sha256"], policy_json=dumps(p["candidate"]), previous_id=prior.id if prior else None))
        event(s, pid, actor, "active"); s.commit()
    storage.kick(); return get(pid)


def rollback(pid, actor, version):
    from engine.scoring import load_base_thresholds
    base = load_base_thresholds()
    with session() as s:
        s.exec(text("BEGIN IMMEDIATE"))
        p = get(pid, s); active = current_activation(s)
        if p["version"] != version or p["status"] != "active" or not active or active.proposal_id != pid :
            raise HTTPException(409, "Only the currently active policy can be rolled back")
        if active.source_base_sha != base.sha256:
            raise HTTPException(409, "Base registry changed; rollback is no longer applicable")
        previous = s.get(PolicyActivation, active.previous_id) if active.previous_id else None
        th = Thresholds.model_validate_json(previous.policy_json) if previous else base
        if previous and previous.source_base_sha != base.sha256:
            th = base
        restored = previous if previous and previous.source_base_sha == base.sha256 else None
        s.add(PolicyActivation(proposal_id=restored.proposal_id if restored else pid, created_at=now(), actor=actor, action="rollback", source_base_sha=base.sha256,
                               policy_sha=th.sha256, policy_json=th.model_dump_json(), previous_id=restored.previous_id if restored else None))
        event(s, pid, actor, "rolled_back", {"from_activation": active.id, "restored_sha": th.sha256})
        if restored:
            event(s, restored.proposal_id, actor, "active", {"restored_by_rollback": pid})
        s.commit()
    storage.kick(); return get(pid)


def recover():
    with session() as s:
        for row in s.exec(select(PolicyProposal)).all():
            p = get(row.id, s)
            if p["status"] == "evaluating":
                event(s, row.id, "Server restart", "rejected", {"reason": "Evaluation interrupted. Clone a new proposal; no incomplete report can be approved."})
        s.commit()
