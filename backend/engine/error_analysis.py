"""Weather-prediction error types, threshold trade-offs and assumed-cost scenarios.

This scores the *weather classification* only: "did the engine flag disruptive weather" against the
independent AMW station label (app/historical.outcome). It says nothing about whether closing,
delaying or staying open was the right operating decision:
  - a false negative is a missed weather disruption, not automatically an unsafe manager decision;
  - a false positive is an unnecessary weather warning under this benchmark, not proof that
    cancelling would have been wrong.
Costs here are assumed, unitless scenario weights for comparing thresholds, never measured losses.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Iterable

MIN_N = 30  # below this many cases in a denominator a rate is reported as "not enough data"
RATIOS = (1, 2, 5, 10, 20, 50)  # missed-disruption cost : false-alarm cost, for sensitivity analysis
COST_LABEL = "Assumed, unitless scenario costs for comparing thresholds. Illustrative only, not measured losses."


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if not n:
        return None
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [max(0.0, center - radius), min(1.0, center + radius)]


def _rate(k: int, n: int, denominator: str) -> dict:
    return {"count": k, "n": n, "denominator": denominator,
            "rate": k / n if n else None, "ci95": wilson(k, n),
            "status": "not enough data" if n < MIN_N else "descriptive estimate",
            "reason": f"No {denominator} in this sample." if not n else None}


def rates(pairs: Iterable[tuple[bool, bool]]) -> dict:
    """(predicted disruptive, observed disruptive) pairs -> both error types with their own denominators."""
    c = Counter((bool(p), bool(a)) for p, a in pairs)
    tp, tn, fp, fn = c[True, True], c[False, False], c[True, False], c[False, True]
    return {
        "n": tp + tn + fp + fn,
        "confusion": {"true_positive": tp, "true_negative": tn, "false_alarm": fp, "missed_disruption": fn},
        # Type I: share of non-disruptive days that were flagged.
        "false_positive_rate": _rate(fp, fp + tn, "non-disruptive days"),
        # Type II: share of disruptive days that were missed (= 1 - recall).
        "false_negative_rate": _rate(fn, fn + tp, "disruptive days"),
        # Not the false-positive rate: its denominator is warnings issued, not quiet days.
        "false_alarm_share_of_warnings": _rate(fp, fp + tp, "warnings issued"),
    }


# Cutoffs on retained signed rule margins (percentage points), not edits to
# scientific thresholds or a full operating-engine rerun. Lower cutoffs warn earlier.
OFFSETS = (-75, -50, -25, -10, 0, 10, 25, 50)


def day_margin(rules: list[dict]) -> float | None:
    """How close a day came to triggering any weather rule, in % of that rule's threshold (>= 0: triggered).

    Uses the engine's own signed margins. An active alert counts as triggered. None: no rule could be
    evaluated (missing data), which is never treated as a quiet day by the sweep: it simply never warns.
    """
    best = None
    for r in rules:
        if not r.get("available"):
            continue
        if r.get("metric") == "alert_present":
            m = 1e9 if r.get("triggered") else None
        else:
            m = r.get("margin_pct")
            if m is None and r.get("triggered"):
                m = 1e9
        if m is not None and (best is None or m > best):
            best = m
    return best


def sweep(rows: Iterable[dict], offsets: Iterable[int] = OFFSETS) -> list[dict]:
    """rows carry margin (day_margin) and observed. Warn when some rule is within the moved threshold."""
    rows = list(rows)
    return [{"offset_pct": o, "current_thresholds": o == 0,
             **rates((r["margin"] is not None and r["margin"] >= o, r["observed"]) for r in rows)} for o in offsets]


def loss(point: dict, c_fp: float, c_fn: float) -> float:
    k = point["confusion"]
    return k["false_alarm"] * c_fp + k["missed_disruption"] * c_fn


def scenario_loss(points: list[dict], c_fp: float, c_fn: float) -> dict:
    losses = [{"offset_pct": p["offset_pct"], "loss": loss(p, c_fp, c_fn)} for p in points]
    # Ties go to the setting closest to today's thresholds.
    best = min(losses, key=lambda x: (x["loss"], abs(x["offset_pct"])))
    return {"assumed": True, "label": COST_LABEL, "false_alarm_cost": c_fp, "missed_disruption_cost": c_fn,
            "losses": losses, "best_offset_pct": best["offset_pct"], "best_loss": best["loss"]}


def sensitivity(points: list[dict], current: dict | None, ratios: Iterable[float] = RATIOS) -> dict:
    out = []
    for r in ratios:
        s = scenario_loss(points, 1, r)
        out.append({"ratio": r, "best_offset_pct": s["best_offset_pct"], "best_loss": s["best_loss"],
                    "current_rules_loss": loss(current, 1, r) if current else None})
    return {"assumed": True, "label": COST_LABEL, "rows": out}


def tradeoff_sentence(points: list[dict]) -> str | None:
    """Plain language: what the next easier threshold setting gains in catches and costs in false alarms."""
    by = {p["offset_pct"]: p for p in points}
    base, easier = by.get(0), [p for p in points if p["offset_pct"] < 0]
    if not base or not easier:
        return None
    k0 = base["confusion"]
    changed = [p for p in sorted(easier, key=lambda p: -p["offset_pct"]) if p["confusion"] != k0]
    if not changed:
        return "Making the thresholds easier to trigger would not change any result in this sample."
    # The smallest change that catches more disruptions; else the smallest change that does anything.
    p = next((p for p in changed if p["confusion"]["true_positive"] > k0["true_positive"]), changed[0])
    caught = p["confusion"]["true_positive"] - k0["true_positive"]
    added = p["confusion"]["false_alarm"] - k0["false_alarm"]
    cost = (f"at the cost of {added} more false alarm{'s' if added != 1 else ''}" if added > 0 else "with no extra false alarms")
    return (f"Making the thresholds {-p['offset_pct']}% easier to trigger would catch {caught} more disruptive "
            f"day{'s' if caught != 1 else ''}, {cost}.")


def analyse(rows: list[dict]) -> dict:
    """rows: {current_prediction, margin, observed} for eligible same-day comparisons.

    "current rules" is what the engine actually flagged (posture other than Normal), which also depends
    on timing; the sweep varies the weather thresholds alone.
    """
    current = rates((r["current_prediction"], r["observed"]) for r in rows)
    points = sweep(rows)
    return {"weather": current, "sweep": points, "sensitivity": sensitivity(points, current),
            "tradeoff": tradeoff_sentence(points) if rows else None,
            "label": "Weather label from local AMW station observations. Not proof that a closure was or was not necessary.",
            "zero_errors_note": "Zero observed errors does not establish zero future risk; see the 95% range."}
