"""Machine-generated 'what would change this recommendation'.

Each statement comes from actually re-running the rules with one input moved
to the other side of a threshold, never from the language model.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from adapters.base import Facility
from engine.features import Context
from engine.posture import decide, decision_day
from engine.scoring import RuleResult, Thresholds, evaluate_rules, score_hazards

NEAR_MISS_FRACTION = 0.6  # untriggered '>=' rules within 60% of threshold are worth mentioning


class Change(BaseModel):
    text: str
    kind: str  # drop_below | rise_above | alert_cleared | alert_issued
    rule_id: str | None = None
    metric: str | None = None
    current_value: float | str | None = None
    threshold: float | None = None
    new_posture: str


def _posture(ctx: Context, th: Thresholds, facility: Facility) -> str:
    rr = evaluate_rules(ctx, th)
    return decide(score_hazards(rr), rr, ctx.as_of, facility, th).posture


def _with_value(ctx: Context, metric: str, value: float) -> Context:
    sigs = dict(ctx.signals)
    s = sigs[metric]
    upd = {"value": value}
    if s.peak_time is None and s.window is None:
        upd["peak_time"] = ctx.as_of
    sigs[metric] = s.model_copy(update=upd)
    return ctx.model_copy(update={"signals": sigs})


SPC_NAMES = ["TSTM", "MRGL", "SLGT", "ENH", "MDT", "HIGH"]
RANK_NAMES = ["normal", "wet/frost", "partially covered", "completely covered", "travel advisory", "not advised/closed"]


def _fmt(v: float, unit: str) -> str:
    if unit.startswith("SPC"):
        return SPC_NAMES[int(v)] if 0 <= int(v) < len(SPC_NAMES) else "none"
    if unit == "rank":
        return f"'{RANK_NAMES[int(v)]}'" if 0 <= int(v) < len(RANK_NAMES) else str(v)
    if unit == "in":
        return f"{v:.2f} in"
    if unit in ("rank", "category", "hours", "sensors") or unit.startswith("SPC"):
        return f"{v:g}"
    return f"{v:.0f} {unit.replace('degF', 'F')}"


def what_would_change(ctx: Context, th: Thresholds, facility: Facility, current: str,
                      results: list[RuleResult], limit: int = 6) -> list[Change]:
    out: list[Change] = []
    rules = {r.id: r for r in th.rules}

    # 1) triggered numeric thresholds: move the value just past the strongest one
    by_metric: dict[str, list[RuleResult]] = {}
    for r in results:
        if r.triggered and r.metric != "alert_present":
            by_metric.setdefault(r.metric, []).append(r)
    for metric, rs in by_metric.items():
        top = max(rs, key=lambda r: (r.level, r.threshold if r.operator in (">=", ">") else -r.threshold))
        eps = 0.001 if top.unit == "in" else 0.1
        hyp = top.threshold - eps if top.operator in (">=", ">") else top.threshold + eps
        p2 = _posture(_with_value(ctx, metric, hyp), th, facility)
        word = "drops below" if top.operator in (">=", ">") else "rises above"
        tail = f"the posture would become {p2}" if p2 != current else f"the posture would stay {current} (other triggers)"
        out.append(Change(
            text=f"If {top.label.lower()} {word} {_fmt(top.threshold, top.unit)} (now {_fmt(float(top.observed_value), top.unit)}), {tail}.",
            kind="drop_below", rule_id=top.rule_id, metric=metric, current_value=top.observed_value,
            threshold=top.threshold, new_posture=p2))

    # 2) alerts in effect: what if they were cancelled / expired
    for r in results:
        if r.triggered and r.metric == "alert_present":
            events = set((rules[r.rule_id].events or []))
            ctx2 = ctx.model_copy(update={"alerts": [a for a in ctx.alerts if a.get("event") not in events]})
            p2 = _posture(ctx2, th, facility)
            tail = f"the posture would become {p2}" if p2 != current else f"the posture would stay {current} (other triggers)"
            out.append(Change(text=f"If the {r.observed_value} were cancelled or expired, {tail}.", kind="alert_cleared",
                              rule_id=r.rule_id, current_value=r.observed_value, new_posture=p2))

    # 3) near misses that would raise the posture
    for r in results:
        if r.triggered or not r.available or r.metric == "alert_present" or r.observed_value is None:
            continue
        v = float(r.observed_value)
        near = (r.operator in (">=", ">") and r.threshold > 0 and v >= NEAR_MISS_FRACTION * r.threshold and v > 0) or \
               (r.operator in ("<=", "<") and v - r.threshold <= 15)
        if not near:
            continue
        p2 = _posture(_with_value(ctx, r.metric, r.threshold), th, facility)
        if p2 != current:
            word = "reaches" if r.operator in (">=", ">") else "falls to"
            out.append(Change(text=f"If {r.label.lower()} {word} {_fmt(r.threshold, r.unit)} (now {_fmt(v, r.unit)}), the posture would become {p2}.",
                              kind="rise_above", rule_id=r.rule_id, metric=r.metric, current_value=v,
                              threshold=r.threshold, new_posture=p2))

    # 4) nothing going on: show how timing alone would move a warning's posture
    if current == "NORMAL" and not any(r.triggered for r in results):
        tz = ZoneInfo(facility.timezone)
        D = decision_day(ctx.as_of, facility)
        for event, start, hours in (("Winter Storm Warning", "04:00", 6), ("Severe Thunderstorm Warning", "14:00", 2)):
            h, m = map(int, start.split(":"))
            s = datetime(D.year, D.month, D.day, h, m, tzinfo=tz).astimezone(ZoneInfo("UTC"))
            fake = {"id": f"hypothetical:{event}", "event": event, "certainty": "Likely", "severity": "Severe",
                    "onset": s.isoformat(), "ends": (s + timedelta(hours=hours)).isoformat()}
            p2 = _posture(ctx.model_copy(update={"alerts": ctx.alerts + [fake]}), th, facility)
            out.append(Change(text=f"If NWS issued a {event} for {start}-{(s + timedelta(hours=hours)).astimezone(tz):%H:%M} on {D:%a %b %d}, the posture would become {p2}.",
                              kind="alert_issued", current_value="none", new_posture=p2))
    return out[:limit]
