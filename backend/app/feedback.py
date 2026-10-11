"""Versioned operational feedback. Opinions and AI text never supply statistical labels."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app import past_decisions, snapshots, storage
from app.db import session
from app.facility import get_facility
from app.historical import binary_metrics
from app.models import (Decision, DecisionAssessment, DecisionContext, DecisionIntent, DecisionReview,
                        FeedbackAnalysis, FeedbackMetric, HistoricalArtifact, HistoricalEvaluation, PolicyActivation, Snapshot)
from engine import error_analysis

DATASET = "operational-feedback-v1"
LABEL = "Completed-day weather disruption; not verified office-operation accuracy"


def now():
    return datetime.now(timezone.utc)


def utc(t):
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def dumps(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


def sha(v):
    return hashlib.sha256(dumps(v).encode()).hexdigest()


def decision_and_snapshot(did):
    with session() as s:
        d = s.get(Decision, did)
    if not d:
        raise HTTPException(404, "Decision not found")
    snap = snapshots.get(d.snapshot_id)
    if not snap:
        raise HTTPException(404, "Recorded weather snapshot not found")
    return d, snap


def annotate(did, actor, objective, reason="", expected_id=None):
    decision_and_snapshot(did)
    with session() as s:
        s.exec(text("BEGIN IMMEDIATE"))
        previous = s.exec(select(DecisionIntent).where(DecisionIntent.decision_id == did).order_by(DecisionIntent.id.desc())).first()
        if expected_id != (previous.id if previous else None):
            raise HTTPException(409, "Intention changed. Refresh before correcting it.")
        if previous and not reason.strip():
            raise HTTPException(422, "Explain why the intention annotation is being corrected")
        row = DecisionIntent(decision_id=did, actor=actor, objective=objective.strip(), created_at=now(),
                             retrospective=True, correction_reason=reason.strip())
        s.add(row); s.commit(); s.refresh(row)
    storage.kick()
    return {**row.model_dump(mode="json"), "created_at": utc(row.created_at).isoformat()}


def classify(posture, actual):
    positive = posture != "NORMAL"
    return ("true_positive" if positive else "missed_disruption") if actual else ("false_alarm" if positive else "true_negative")


def record_assessment(d, snap, outcome, at, actor="Weather archive"):
    start, end = past_decisions.day_window(snap["posture"]["decision_day"], snap.get("facility", {}).get("timezone") or get_facility(d.facility_id).timezone)
    coverage = outcome.get("coverage") or {}
    complete = bool(coverage.get("complete"))
    eligible = utc(at) >= end and complete and isinstance(outcome.get("severe_impact"), bool)
    manager = classify(d.decision_posture, outcome["severe_impact"]) if eligible else None
    recommendation = classify(d.recommended_posture, outcome["severe_impact"]) if eligible else None
    good = {"true_positive", "true_negative"}
    comparison = ("same weather-classification result" if manager == recommendation else
                  "override improved weather classification" if manager in good and recommendation not in good else
                  "override worsened weather classification" if recommendation in good and manager not in good else "inconclusive") if eligible else "cannot assess"
    evidence = {"dataset": DATASET, "label_version": "completed-weather-v1", "label": LABEL,
                "decision_id": d.id, "snapshot_id": d.snapshot_id, "decision_day": snap["posture"]["decision_day"],
                "period": {"start": start.isoformat(), "end": end.isoformat()},
                "thresholds_sha": snap.get("thresholds_sha256"), "thresholds_version": snap.get("thresholds_version"),
                "eligible": eligible, "status": "complete" if eligible else "insufficient_evidence",
                "outcome": outcome, "manager_weather_classification": manager,
                "recommendation_weather_classification": recommendation, "comparison": comparison,
                "action_assessment": "Not enough independently verified operating-action/timing labels. Weather classification is not proof that closing or staying open was right.",
                "exclusion_reason": None if eligible else "Day incomplete or insufficient independently observed weather coverage"}
    digest = sha({"decision": d.id, "evidence": evidence})
    with session() as s:
        s.exec(text("BEGIN IMMEDIATE"))
        existing = s.exec(select(DecisionAssessment).where(DecisionAssessment.decision_id == d.id,
                                                          DecisionAssessment.content_sha256 == digest)).first()
        if existing:
            return json.loads(existing.evidence_json)
        s.add(DecisionAssessment(decision_id=d.id, created_at=at, actor=actor, content_sha256=digest, evidence_json=dumps(evidence)))
        s.commit()
    storage.kick()
    return evidence


def detail(did):
    d, snap = decision_and_snapshot(did)
    with session() as s:
        intents = s.exec(select(DecisionIntent).where(DecisionIntent.decision_id == did).order_by(DecisionIntent.id.desc())).all()
        reviews = s.exec(select(DecisionReview).where(DecisionReview.decision_id == did).order_by(DecisionReview.id.desc())).all()
        assessments = s.exec(select(DecisionAssessment).where(DecisionAssessment.decision_id == did).order_by(DecisionAssessment.id.desc())).all()
        ctx = s.get(DecisionContext, did)
    tz = snap.get("facility", {}).get("timezone") or get_facility(d.facility_id).timezone
    _, end = past_decisions.day_window(snap["posture"]["decision_day"], tz)
    return {"decision": {**d.model_dump(mode="json"), "decided_at": utc(d.decided_at).isoformat()}, "facility": snap.get("facility", {"id": d.facility_id, "timezone": tz}),
            "decision_day": snap["posture"]["decision_day"], "timezone": tz,
            "recommended_reason": snap["posture"].get("reasons", []),
            "thresholds_sha": snap.get("thresholds_sha256"), "thresholds_version": snap.get("thresholds_version"),
            "agreed": d.decision_posture == d.recommended_posture,
            "status": "pending" if now() < end else "reviewable", "period_end": end.isoformat(),
            "demo_or_example": snap["mode"] != "live" or not ctx or ctx.demo_mode or ctx.example,
            "intentions": [{**r.model_dump(mode="json"), "created_at": utc(r.created_at).isoformat()} for r in intents],
            "reviews": [{**r.model_dump(mode="json"), "created_at": utc(r.created_at).isoformat(), "evidence": json.loads(r.evidence_json)} for r in reviews],
            "assessments": [{"id": r.id, "created_at": utc(r.created_at).isoformat(), "hash": r.content_sha256,
                             **json.loads(r.evidence_json)} for r in assessments]}


def measures(pairs, c_fp=1, c_fn=5):
    pairs = list(pairs)
    result = {**binary_metrics(pairs), **error_analysis.rates(pairs)}
    n = result["n"]
    k = result["confusion"]
    result.update(weighted_loss=error_analysis.loss(result, c_fp, c_fn),
                  status="not enough data" if n < error_analysis.MIN_N else "descriptive estimate",
                  denominator="One first operating decision per facility/local day",
                  metric_status={"accuracy": "not enough data" if not n else "descriptive estimate",
                                 "balanced_accuracy": "not enough data" if result["balanced_accuracy"] is None else "descriptive estimate",
                                 "precision": "not enough data" if not k["true_positive"] + k["false_alarm"] else "descriptive estimate",
                                 "recall": "not enough data" if not k["true_positive"] + k["missed_disruption"] else "descriptive estimate"},
                  definitions={"accuracy": "Correct classifications / eligible days", "balanced_accuracy": "(recall + specificity) / 2",
                               "precision": "Detected disruptions / warnings", "recall": "Detected disruptions / disruptive days",
                               "specificity": "Correct quiet days / quiet days", "false_positive_rate": "False alarms / quiet days",
                               "false_negative_rate": "Misses / disruptive days"})
    return result


def catalog():
    with session() as s:
        counts = {name: s.exec(select(func.count()).select_from(cls)).one() for name, cls in
                  (("intentions", DecisionIntent), ("reviews", DecisionReview), ("assessments", DecisionAssessment), ("metric_runs", FeedbackMetric))}
    return {"id": DATASET, "label": "Private operational feedback; separate from historical weather benchmarks", "counts": counts,
            "cloud_prefix": "feedback/", "private": True, "github_export": False}


def benchmark_measures(rows, manifest_bytes, c_fp, c_fn):
    """Stored benchmark predictions, always separate from operational-manager accuracy."""
    from zoneinfo import ZoneInfo
    from engine.posture import decision_day
    from app.facility import load_facility
    f = load_facility()
    by_id = {rid:(artifact, raw) for rid, artifact, raw in rows}
    baseline, baseline_status = [], "Frozen manifest unavailable"
    try:
        manifest = json.loads(manifest_bytes) if manifest_bytes else None
    except ValueError:
        manifest = None
        baseline_status = "Frozen manifest is unreadable; historical baseline excluded"
    if manifest:
        valid = manifest.get("n") == 7470 and len(manifest.get("entries", [])) == 7470 and len({e["day"] for e in manifest.get("entries", [])}) == 7470 and manifest.get("cohort_sha") == sha(manifest.get("entries", []))
        for entry in manifest.get("entries", []):
            item = by_id.get(entry["id"])
            if not item or item[0] != entry.get("artifact_sha") or hashlib.sha256(item[1].encode()).hexdigest() != entry.get("summary_sha"):
                valid = False; break
            v = json.loads(item[1]); baseline.append((v["recommendation"] != "NORMAL", v["outcome"]["disruptive"]))
        if not valid:
            baseline = []; baseline_status = "Frozen manifest integrity mismatch or missing records"
        else:
            baseline_status = "Preserved recorded benchmark; observation-only, not advance warning"
    forecast, excluded = {}, Counter()
    for rid, artifact, raw in rows:
        v = json.loads(raw)
        if v.get("requested_mode") != "archive" or "forecast reconstruction" not in v.get("reconstruction", ""):
            continue
        t = datetime.fromisoformat(v["as_of"])
        day = v.get("day")
        if (not v.get("selection_gradable") or not v.get("outcome", {}).get("gradable") or not v.get("recommendation")
            or t.astimezone(ZoneInfo(f.timezone)).strftime("%H:%M") != "04:00"
            or str(v.get("decision_day") or decision_day(t, f)) != day):
            excluded["Incomplete, not same day, or not 04:00"] += 1; continue
        from app.policy import safe_inputs
        import gzip
        with session() as s:
            blob = s.get(HistoricalArtifact, artifact) if artifact else None
        if not blob or hashlib.sha256(blob.payload).hexdigest() != artifact:
            excluded["Missing or corrupt retained forecast artifact"] += 1; continue
        retained = json.loads(gzip.decompress(blob.payload))
        if not safe_inputs(retained) or not any(i["role"] == "forecast" and i["kind"] == "series" for i in retained["inputs"]):
            excluded["Future/uncertain forecast or observation availability"] += 1; continue
        forecast.setdefault(day, {"prediction":v["recommendation"] != "NORMAL", "observed":v["outcome"]["disruptive"],
                                  "rules_sha":v.get("rules_sha"),"artifact_sha":artifact})
    return {"frozen_baseline": {"id":"ames-7470-v1", "status":baseline_status, "metrics":measures(baseline,c_fp,c_fn),
                               "cohort_sha":manifest.get("cohort_sha") if manifest else None},
            "forecast_dataset": {"id":"retained-04:00-forecast-inputs", "metrics":measures(((v["prediction"],v["observed"]) for v in forecast.values()),c_fp,c_fn),
                                 "cohort_sha":sha(forecast),"excluded":dict(excluded), "rule_hashes":dict(Counter(v["rules_sha"] for v in forecast.values())),
                                 "label":"Stored retrospective forecast predictions; potentially different recorded rule versions"},
            "hourly_validation": "Separate recall-hourly.json results; never pooled with unique days", "pooled":False,
            "limitation":"Benchmarks use local station disruption labels, not confirmed USDA closures; no notice never means open."}


def intent_category(objective):
    # Aggregate only these fixed labels; free text never goes to inference.
    text = objective.lower()
    if any(w in text for w in ("injury", "safety", "safe", "commute")):
        return "worker_safety"
    if any(w in text for w in ("income", "cost", "productivity", "continuity", "task")):
        return "operational_continuity"
    return "other"


def statistics(c_fp=1., c_fn=5.):
    with session() as s:
        s.exec(text("BEGIN"))  # one consistent read snapshot for the cache fingerprint
        historical = s.exec(select(HistoricalEvaluation.id, HistoricalEvaluation.artifact_sha, HistoricalEvaluation.summary_json)).all()
        historical_sha = sha([(r[0], r[1], hashlib.sha256(r[2].encode()).hexdigest()) for r in sorted(historical)])
        from app.risk_experiment import manifest_path
        manifest_bytes = manifest_path().read_bytes() if manifest_path().exists() else b""
        activation = s.exec(select(PolicyActivation).order_by(PolicyActivation.id.desc())).first()
        marks = [(s.exec(select(func.max(cls.id))).one(), s.exec(select(func.count()).select_from(cls)).one())
                 for cls in (Decision, DecisionIntent, DecisionReview, DecisionAssessment)]
        marks.append((s.exec(select(func.max(DecisionContext.decision_id))).one(), s.exec(select(func.count()).select_from(DecisionContext)).one()))
        watermark = {"tables": marks, "costs": [c_fp, c_fn], "method": DATASET + ":first-decision-v5", "historical_sha": historical_sha, "manifest_sha": hashlib.sha256(manifest_bytes).hexdigest(), "activation_id": activation.id if activation else None}
        key = sha(watermark)
        cached = s.get(FeedbackMetric, key)
        if cached:
            return {"id": key, "updated_at": utc(cached.created_at).isoformat(), **json.loads(cached.summary_json)}
        decisions = s.exec(select(Decision).order_by(Decision.decided_at, Decision.id)).all()
        snaps = {r.snapshot_id: r for r in s.exec(select(Snapshot)).all()}
        contexts = {r.decision_id: r for r in s.exec(select(DecisionContext)).all()}
        latest = {}
        for r in s.exec(select(DecisionAssessment).order_by(DecisionAssessment.id)).all():
            latest[r.decision_id] = json.loads(r.evidence_json)
        reviews = s.exec(select(DecisionReview)).all()
        intentions = s.exec(select(DecisionIntent).order_by(DecisionIntent.id)).all()
    latest_reviews = {r.decision_id:r for r in sorted(reviews,key=lambda r:r.id) if r.source == "manager"}
    real_ids = {d.id for d in decisions if d.snapshot_id in snaps and snaps[d.snapshot_id].mode == "live"
                and d.id in contexts and not contexts[d.id].demo_mode and not contexts[d.id].example}
    opinion_reviews = [r for r in latest_reviews.values() if r.decision_id in real_ids]
    seen, excluded, used, manager, engine = set(), Counter(), [], [], []
    versions, hazards, by_year = Counter(), defaultdict(list), defaultdict(list)
    comparisons = Counter()
    agreements = 0
    prospective = []
    for d in decisions:
        snap, ctx = snaps.get(d.snapshot_id), contexts.get(d.id)
        if not snap or snap.mode != "live" or not ctx or ctx.demo_mode or ctx.example:
            excluded["Demo/example/non-live or missing decision context"] += 1; continue
        day = json.loads(snap.posture_json).get("decision_day")
        if not day:
            excluded["Missing decision day"] += 1; continue
        unit = (d.facility_id, day)
        if unit in seen:
            excluded["Follow-up decision for the same facility/local day"] += 1; continue
        seen.add(unit)
        if ctx.evidence_status not in ("sufficient", "limited"):
            excluded["Insufficient or unrecorded decision-time evidence; fallback is not a prediction"] += 1; continue
        observed = latest.get(d.id)
        if not observed or not observed["eligible"]:
            excluded["Pending or insufficient independently observed outcomes"] += 1; continue
        latest_review = latest_reviews.get(d.id)
        if latest_review and json.loads(latest_review.evidence_json).get("observed_evidence_status") == "disputed":
            excluded["Observed evidence disputed by manager; resolution required"] += 1; continue
        actual = observed["outcome"]["severe_impact"]
        comparisons[observed["comparison"]] += 1
        if activation and utc(d.decided_at) >= utc(activation.created_at) and snap.thresholds_sha256 == activation.policy_sha:
            prospective.append((d.decision_posture != "NORMAL", actual))
        manager.append((d.decision_posture != "NORMAL", actual))
        engine.append((d.recommended_posture != "NORMAL", actual))
        agreements += d.decision_posture == d.recommended_posture
        used.append({"decision_id": d.id, "facility_id": d.facility_id, "day": day, "outcome_sha": sha(observed)})
        versions[snap.thresholds_version] += 1
        by_year[day[:4]].append((manager[-1], engine[-1]))
        active = [k for k, v in json.loads(snap.hazards_json).items() if v.get("level", 0) > 0] or ["none_recorded"]
        for hazard in active:
            hazards[hazard].append((manager[-1], engine[-1]))
    def breakdown(group):
        return {key: {"manager": measures((x[0] for x in rows), c_fp, c_fn), "recommendation": measures((x[1] for x in rows), c_fp, c_fn)}
                for key, rows in group.items()}
    body = {"dataset": DATASET, "label": LABEL, "watermark": watermark, "cohort_sha": sha(used), "records": used,
            "costs": {"false_alarm": c_fp, "missed_disruption": c_fn, "assumed": True, "units": "unitless, not measured injury or income losses"},
            "manager": measures(manager, c_fp, c_fn), "recommendation": measures(engine, c_fp, c_fn),
            "agreement": {"n": len(used), "count": agreements, "rate": agreements / len(used) if used else None, "label": "Agreement, not accuracy"},
            "excluded": dict(excluded), "eligible_count": len(used), "excluded_count": sum(excluded.values()),
            "range": {"start": min((r["day"] for r in used), default=None), "end": max((r["day"] for r in used), default=None)},
            "rule_versions": dict(versions), "hazards": breakdown(hazards), "years": breakdown(by_year),
            "override_comparisons": dict(comparisons),
            "objective_achievement_opinions": dict(Counter(json.loads(r.evidence_json).get("achievement","unknown") for r in opinion_reviews)),
            "override_reason_categories": dict(Counter(intent_category(d.override_reason or d.notes or "") for d in decisions if d.id in real_ids)),
            "intent_categories": dict(Counter(intent_category(r.objective) for r in {r.decision_id:r for r in intentions}.values() if r.decision_id in real_ids)),
            "manager_opinions": dict(Counter(r.verdict for r in opinion_reviews)),
            "confirmed_operating_decisions": {"n": 0, "status": "not enough data", "multiclass_accuracy": None,
                                               "reason": "No independently verified facility operating-action labels have been imported. Opinions and proxy closures are excluded."},
            "historical_benchmarks": benchmark_measures(historical, manifest_bytes, c_fp, c_fn),
            "prospective": {"manager": measures(prospective, c_fp, c_fn), "activation_id": activation.id if activation else None,
                            "since": utc(activation.created_at).isoformat() if activation else None, "label": "Future first decisions made after the latest activation; observed weather only"},
            "limitations": ["Binary positive means non-normal posture; observed positive means completed-day weather disruption.",
                            "Weather classification does not establish correct reporting times or closure necessity.",
                            "One first decision per facility/local day avoids selecting a later call with hindsight.",
                            "Consecutive storm days and hourly checks are correlated. Wilson intervals are descriptive and do not correct that correlation.",
                            "Rare disruptions and small samples limit recall estimates; no injury or financial outcomes are measured.",
                            "Manager reviews and Akamai interpretations never become independent statistical labels."]}
    with session() as s:
        row = FeedbackMetric(id=key, created_at=now(), summary_json=dumps(body))
        try:
            s.add(row); s.commit(); s.refresh(row)
        except IntegrityError:
            s.rollback(); row = s.get(FeedbackMetric, key)
    storage.kick()
    return {"id": key, "updated_at": utc(row.created_at).isoformat(), **body}


async def analyze(actor, c_fp=1., c_fn=5.):
    """One durable request claim per statistics fingerprint. GETs never call inference."""
    from ai.feedback import explain
    metric = statistics(c_fp, c_fn)
    from app.config import settings
    fingerprint = sha({"metric": metric["id"], "prompt": "feedback-v1", "provider": settings.model_provider,
                       "model": settings.akamai_model_id, "configured": bool(settings.akamai_api_key)})
    rid = "request-" + fingerprint
    result_id = "result-" + fingerprint
    with session() as s:
        s.exec(text("BEGIN IMMEDIATE"))
        existing = s.get(FeedbackAnalysis, result_id)
        if existing:
            return json.loads(existing.payload_json)
        request = s.get(FeedbackAnalysis, rid)
        if request:
            if (now() - utc(request.created_at)).total_seconds() <= 65:
                return {"status": "pending", "metric_id": metric["id"], "source": "template", "explanation": "Analysis is in progress. Refresh results shortly."}
            result = {"status": "failed", "source": "template", "id": result_id, "metric_id": metric["id"], "explanation": "Analysis was interrupted. Updated statistics remain available; a new statistics version can be analyzed.", "proposals": []}
            s.add(FeedbackAnalysis(id=result_id, metric_id=metric["id"], actor=actor, created_at=now(), payload_json=dumps(result)))
            s.commit(); storage.kick(); return result
        s.add(FeedbackAnalysis(id=rid, metric_id=metric["id"], actor=actor, created_at=now(), payload_json=dumps({"status": "requested", "prompt_version": "feedback-v1"})))
        s.commit()
    result = await explain(metric)
    result.update(id=result_id, metric_id=metric["id"], created_at=now().isoformat())
    with session() as s:
        s.exec(text("BEGIN IMMEDIATE"))
        existing = s.get(FeedbackAnalysis, result_id)
        if existing:
            return json.loads(existing.payload_json)
        s.add(FeedbackAnalysis(id=result_id, metric_id=metric["id"], actor=actor, created_at=now(), payload_json=dumps(result))); s.commit()
    storage.kick()
    return result


def latest_analysis():
    with session() as s:
        rows = s.exec(select(FeedbackAnalysis).where(FeedbackAnalysis.id.startswith("result-")).order_by(FeedbackAnalysis.created_at.desc())).first()
    return json.loads(rows.payload_json) if rows else None
