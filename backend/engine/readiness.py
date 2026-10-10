"""Decision-maker readiness, adapted from Cooper's Color Code (WHITE / YELLOW / ORANGE / RED).

The posture says what to do; readiness says how closely to watch and how soon a decision
is due. Deterministic, from the same snapshot; cutoffs live in thresholds.yaml `readiness`.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from adapters.base import Facility, utc
from engine.confidence import Confidence
from engine.posture import PostureResult, _at
from engine.scoring import HazardResult, RuleResult, Thresholds

LEVELS = ["WHITE", "YELLOW", "ORANGE", "RED"]


class Readiness(BaseModel):
    level: str
    cooper: str
    meaning: str
    reasons: list[str]
    decide_by: datetime | None = None
    deadline_passed: bool = False
    recheck_minutes: int
    basis: str = "policy (adapted from Cooper's Color Code; not a federal standard)"


def decision_deadline(posture: PostureResult, hazards: dict[str, HazardResult], rules: list[RuleResult],
                      as_of: datetime, facility: Facility, cfg: dict) -> datetime | None:
    """When the posture must be announced: before the AM commute, or ahead of an arriving hazard."""
    p = posture.posture
    if p in ("DELAYED_ARRIVAL", "TELEWORK", "CLOSED"):
        return _at(posture.decision_day, cfg["announce_by"], ZoneInfo(facility.timezone))
    if p == "EARLY_DISMISSAL":
        starts = [r.window_start for r in rules if r.triggered and r.level >= 2 and r.window_start
                  and r.hazard in posture.contributing_hazards]
        if starts:
            return max(utc(as_of), utc(min(starts)) - timedelta(hours=int(cfg["release_lead_hours"])))
        return utc(as_of)
    return None


def _near_misses(rules: list[RuleResult], frac: float) -> list[RuleResult]:
    out = []
    for r in rules:
        if r.triggered or not r.available or r.metric == "alert_present" or not isinstance(r.observed_value, (int, float)):
            continue
        v = float(r.observed_value)
        if (r.operator in (">=", ">") and r.threshold > 0 and v > 0 and v >= frac * r.threshold) or \
           (r.operator in ("<=", "<") and v - r.threshold <= 15):
            out.append(r)
    return out


def assess_readiness(hazards: dict[str, HazardResult], rules: list[RuleResult], posture: PostureResult,
                     confidence: Confidence, alerts: list[dict], as_of: datetime, facility: Facility,
                     th: Thresholds) -> Readiness:
    cfg = th.raw["readiness"]
    now = utc(as_of)
    tz = ZoneInfo(facility.timezone)
    red_h = timedelta(hours=float(cfg["red_within_hours"]))
    fmt = lambda t: utc(t).astimezone(tz).strftime("%a %H:%M %Z")  # noqa: E731
    found: dict[str, list[str]] = {lv: [] for lv in LEVELS}

    deadline = decision_deadline(posture, hazards, rules, now, facility, cfg)
    passed = deadline is not None and deadline <= now

    # RED: act now
    if posture.guidance:
        found["RED"].append("Safety guidance is active: " + posture.guidance[0])
    for r in rules:
        if r.triggered and r.level >= 2 and r.window_start:
            end = r.window_end or r.window_start + timedelta(hours=6)
            if utc(r.window_start) <= now < utc(end):
                found["RED"].append(f"{r.observed_value if r.metric == 'alert_present' else r.label} is happening now")
            elif now < utc(r.window_start) <= now + red_h:
                found["RED"].append(f"{r.observed_value if r.metric == 'alert_present' else r.label} begins {fmt(r.window_start)}")
    if deadline is not None and deadline - now <= red_h and now - deadline <= timedelta(hours=4):
        found["RED"].append(f"{posture.posture.replace('_', ' ').title()} must be announced by {fmt(deadline)}"
                            + (" (deadline has passed)" if passed else ""))

    # ORANGE: specific threat identified
    if posture.posture != "NORMAL":
        found["ORANGE"].append(f"{posture.posture.replace('_', ' ').title()} recommended for {posture.decision_day:%a %b %d}"
                               + (f"; announce by {fmt(deadline)}" if deadline else ""))
    for hz in hazards.values():
        if hz.level >= 2:
            found["ORANGE"].append(f"{hz.label} is {hz.level_name}")
    for a in alerts:
        if "Warning" in (a.get("event") or ""):
            found["ORANGE"].append(f"{a['event']} in effect or issued")

    # YELLOW: relaxed alert
    for hz in hazards.values():
        if hz.level == 1:
            found["YELLOW"].append(f"{hz.label} is minor")
    for a in alerts:
        ev = a.get("event") or ""
        if "Watch" in ev or "Advisory" in ev:
            found["YELLOW"].append(f"{ev} in effect or issued")
    for r in _near_misses(rules, float(cfg["near_miss_fraction"])):
        found["YELLOW"].append(f"{r.label} is {r.observed_value:g} {r.unit}, approaching {r.threshold:g}")
    if confidence.level == "low":
        found["YELLOW"].append("Confidence is low: data is incomplete or stale, so stay alert")

    level = next((lv for lv in reversed(LEVELS) if found[lv]), "WHITE")
    reasons = list(dict.fromkeys(found[level])) or ["No alerts, hazards or near-miss forecasts in the window"]
    meta = cfg["levels"][level]
    return Readiness(level=level, cooper=meta["cooper"], meaning=meta["meaning"], reasons=reasons[:5],
                     decide_by=deadline, deadline_passed=passed, recheck_minutes=int(meta["recheck_minutes"]))
