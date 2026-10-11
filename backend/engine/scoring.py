"""Threshold evaluation (with margins and timing) and per-hazard scoring."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from engine.features import Context, Signal, parse_ts

THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / "config" / "thresholds.yaml"
LEVELS = {"none": 0, "minor": 1, "significant": 2, "extreme": 3}
LEVEL_NAMES = {v: k for k, v in LEVELS.items()}
HAZARDS = {"winter": "Winter / ice", "wind": "High wind / severe thunderstorm", "cold": "Extreme cold"}
COASTAL_HAZARDS = {"tropical": "Tropical storm / hurricane", "coastal": "Storm surge / coastal flooding", "flood": "Inland / flash flooding", "access": "Commute access disruption"}
ALERT_LOOKAHEAD = timedelta(hours=36)


class Rule(BaseModel):
    id: str
    hazard: str
    metric: str
    operator: str
    value: float
    unit: str
    posture_effect: str
    score: int
    time_window: str
    anchor: str
    source_url: str
    verified: bool
    basis: str = "official"
    events: list[str] | None = None
    planning_only: bool = False
    lookahead_hours: int = 36


class Thresholds(BaseModel):
    version: str
    sha256: str
    rules: list[Rule]
    postures: dict[str, Any]
    timing: dict[str, Any]
    raw: dict[str, Any]


@lru_cache
def _load_thresholds(path: str | None = None) -> Thresholds:
    p = Path(path) if path else THRESHOLDS_PATH
    # Hash with LF line endings so a Windows checkout (CRLF) identifies the same rules as Linux and the datasets.
    text = p.read_bytes().replace(b"\r\n", b"\n")
    raw = yaml.safe_load(text)
    return Thresholds(
        version=raw["version"],
        sha256=hashlib.sha256(text).hexdigest(),
        rules=[Rule(**r) for r in raw["rules"]],
        postures=raw["postures"],
        timing=raw["timing"],
        raw=raw,
    )


@lru_cache
def _wilmington_thresholds() -> Thresholds:
    """A separate policy profile: Ames' rule file, hash, and saved results remain unchanged."""
    base = load_thresholds()
    overlay_text = (THRESHOLDS_PATH.parent / "thresholds-wilmington.yaml").read_bytes().replace(b"\r\n", b"\n")
    overlay = yaml.safe_load(overlay_text)
    raw = {**base.raw, **{k: v for k, v in overlay.items() if k not in ("rules", "remove_rules", "rule_overrides")}}
    excluded = set(overlay.get("remove_rules", []))
    overrides = overlay.get("rule_overrides", {})
    raw["rules"] = [{**r, **overrides.get(r["id"], {})} for r in base.raw["rules"] if r["id"] not in excluded] + overlay["rules"]
    return Thresholds(version=raw["version"], sha256=hashlib.sha256((base.sha256 + "\n").encode() + overlay_text).hexdigest(),
                      rules=[Rule(**r) for r in raw["rules"]], postures=raw["postures"], timing=raw["timing"], raw=raw)


def load_thresholds(path: str | None = None, facility=None) -> Thresholds:
    if path:
        return _load_thresholds(path)
    if facility is not None and (getattr(facility, "threshold_profile", None) == "wilmington"
                                 or getattr(facility, "policy_profile", None) == "wilmington"
                                 or facility.state == "NC"):
        return _wilmington_thresholds()
    return _load_thresholds()


# Keep the longstanding test/development cache-clear interface.
def _clear_thresholds_cache():
    _load_thresholds.cache_clear()
    _wilmington_thresholds.cache_clear()


load_thresholds.cache_clear = _clear_thresholds_cache


class RuleResult(BaseModel):
    rule_id: str
    hazard: str
    metric: str
    label: str
    operator: str
    threshold: float
    unit: str
    observed_value: float | str | None
    triggered: bool
    available: bool
    margin_abs: float | None = None
    margin_pct: float | None = None
    time_of_peak: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    input_ids: list[str] = []
    level: int
    posture_effect: str
    score: int
    verified: bool
    basis: str
    anchor: str
    source_url: str
    time_window: str
    detail: str | None = None
    planning_only: bool = False
    hazard_timing_known: bool = True


class HazardResult(BaseModel):
    hazard: str
    label: str
    score: int
    level: int
    level_name: str
    triggered_rule_ids: list[str]
    controlling_rule_ids: list[str]
    window_start: datetime | None = None
    window_end: datetime | None = None
    time_of_peak: datetime | None = None
    posture: str = "NORMAL"
    posture_reason: str = ""
    planning_only: bool = False
    hazard_timing_known: bool = True


def _cmp(v: float, op: str, thr: float) -> bool:
    return {">=": v >= thr, ">": v > thr, "<=": v <= thr, "<": v < thr}[op]


def _margin(v: float, op: str, thr: float) -> tuple[float, float | None]:
    m = v - thr if op in (">=", ">") else thr - v
    pct = None if thr == 0 else m / abs(thr) * 100
    return round(m, 3), None if pct is None else round(pct, 1)


def _numeric_window(sig: Signal, op: str, thr: float) -> tuple[datetime | None, datetime | None]:
    if sig.window:
        return sig.window
    if not sig.hourly:
        return None, None
    if sig.accumulation:
        hours = [t for t, v in sig.hourly if v > 0.0005]
    else:
        hours = [t for t, v in sig.hourly if _cmp(v, op, thr)]
    if not hours:
        return None, None
    return min(hours), max(hours) + timedelta(hours=1)


def _alert_window(a: dict) -> tuple[datetime | None, datetime | None]:
    start = parse_ts(a.get("onset")) or parse_ts(a.get("effective")) or parse_ts(a.get("sent"))
    end = parse_ts(a.get("ends")) or parse_ts(a.get("expires"))
    return start, end


def evaluate_rule(rule: Rule, ctx: Context) -> RuleResult:
    base = dict(rule_id=rule.id, hazard=rule.hazard, metric=rule.metric, operator=rule.operator, threshold=rule.value,
                unit=rule.unit, level=LEVELS[rule.posture_effect], posture_effect=rule.posture_effect, score=rule.score,
                verified=rule.verified, basis=rule.basis, anchor=rule.anchor, source_url=rule.source_url,
                time_window=rule.time_window, planning_only=rule.planning_only)
    if rule.metric == "alert_present":
        label = " / ".join(rule.events or [])
        hits = []
        for a in ctx.alerts:
            if a.get("event") not in (rule.events or []):
                continue
            s, e = _alert_window(a)
            issued = parse_ts(a.get("sent"))
            if issued is not None and issued > ctx.as_of:
                continue
            if e is not None and e < ctx.as_of:
                continue
            if s is not None and s > max(ctx.as_of + timedelta(hours=rule.lookahead_hours), ctx.horizon_end):
                continue
            hits.append((a, s, e))
        if not hits:
            return RuleResult(**base, label=label, observed_value="not in effect", triggered=False, available=True)
        starts = [s for _, s, _ in hits if s]
        ends = [e for _, _, e in hits if e]
        # A hurricane warning's effective timestamp is an announcement, not local wind arrival.
        issued_warning_timing = rule.hazard == "tropical" or (rule.hazard == "coastal" and any("Storm Surge" in a.get("event", "") for a, _, _ in hits))
        timing_known = not issued_warning_timing or all(
            parse_ts(a.get("onset")) is not None
            and parse_ts(a.get("onset")) > (parse_ts(a.get("effective")) or parse_ts(a.get("sent")) or ctx.as_of)
            for a, _, _ in hits)
        timing_note = " Warning-effective interval; local hazard arrival time is not established." if not timing_known else ""
        return RuleResult(
            **base, label=label, observed_value=", ".join(sorted({a["event"] for a, _, _ in hits})), triggered=True,
            available=True, time_of_peak=min(starts) if starts else None,
            window_start=min(starts) if starts else ctx.as_of, window_end=max(ends) if ends else None,
            input_ids=[ctx.alert_input_ids.get(a["id"], a["id"]) for a, _, _ in hits],
            hazard_timing_known=timing_known,
            detail="; ".join(f"{a['event']} ({a.get('certainty')}/{a.get('severity')}) {a.get('onset') or ''} to {a.get('ends') or a.get('expires') or ''}" for a, _, _ in hits) + timing_note,
        )
    sig = ctx.signals.get(rule.metric)
    if sig is None or not sig.available or sig.value is None:
        return RuleResult(**base, label=sig.label if sig else rule.metric, observed_value=None, triggered=False,
                          available=False, detail=sig.detail if sig else "signal not computed")
    v = float(sig.value)
    trig = _cmp(v, rule.operator, rule.value)
    m, pct = _margin(v, rule.operator, rule.value)
    ws, we = _numeric_window(sig, rule.operator, rule.value) if trig else (None, None)
    return RuleResult(**base, label=sig.label, observed_value=v, triggered=trig, available=True, margin_abs=m,
                      margin_pct=pct, time_of_peak=sig.peak_time, window_start=ws, window_end=we,
                      input_ids=sig.input_ids, detail=sig.detail)


def evaluate_rules(ctx: Context, thresholds: Thresholds) -> list[RuleResult]:
    return [evaluate_rule(r, ctx) for r in thresholds.rules]


def score_hazards(results: list[RuleResult]) -> dict[str, HazardResult]:
    out = {}
    active_families = {r.hazard for r in results}
    labels = {**HAZARDS, **{h: label for h, label in COASTAL_HAZARDS.items() if h in active_families}}
    for hz, label in labels.items():
        trig = [r for r in results if r.hazard == hz and r.triggered]
        if not trig:
            out[hz] = HazardResult(hazard=hz, label=label, score=0, level=0, level_name="none",
                                   triggered_rule_ids=[], controlling_rule_ids=[])
            continue
        level = max(r.level for r in trig)
        ctrl = [r for r in trig if r.level == level]
        top = max(r.score for r in trig)
        score = min(100, top + 5 * (len(trig) - 1))
        starts = [r.window_start for r in ctrl if r.window_start]
        ends = [r.window_end for r in ctrl if r.window_end]
        peaks = [r.time_of_peak for r in ctrl if r.time_of_peak]
        out[hz] = HazardResult(
            hazard=hz, label=label, score=score, level=level, level_name=LEVEL_NAMES[level],
            triggered_rule_ids=[r.rule_id for r in trig], controlling_rule_ids=[r.rule_id for r in ctrl],
            window_start=min(starts) if starts else None, window_end=max(ends) if ends else None,
            time_of_peak=min(peaks) if peaks else None,
            planning_only=all(r.planning_only for r in trig),
            hazard_timing_known=all(r.hazard_timing_known for r in ctrl),
        )
    return out
