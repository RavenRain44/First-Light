"""Deterministic, template-based interpretation.

Used when no model credentials are configured, when the model call fails, or
when its output fails validation. The dashboard is fully usable on this alone.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ai.prompts import Interpretation

POSTURE_WORDS = {
    "NORMAL": "operate normally",
    "DELAYED_ARRIVAL": "open on a delayed arrival",
    "EARLY_DISMISSAL": "release employees early",
    "TELEWORK": "open with unscheduled leave or unscheduled telework",
    "CLOSED": "close the office",
}


def _local(ts: str | None, tz: ZoneInfo) -> str:
    if not ts:
        return "unknown time"
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(tz).strftime("%a %H:%M %Z")


def _article(word: str) -> str:
    return "an" if word[:1].upper() in "AEIOU" else "a"


def _fmt_val(v, unit: str) -> str:
    if isinstance(v, str):
        return v
    if v is None:
        return "unavailable"
    if unit == "in":
        return f"{v:.2f} in"
    if unit == "mph":
        return f"{v:.0f} mph"
    if unit == "degF":
        return f"{v:.0f} F"
    return f"{v:g} {unit}"


def alert_line(a: dict, tz: ZoneInfo) -> str:
    sev = a.get("severity") or "Unknown"
    cert = a.get("certainty") or "Unknown"
    return f"{a.get('event')} ({sev}, {cert}) from {_local(a.get('onset') or a.get('effective'), tz)} to {_local(a.get('ends') or a.get('expires'), tz)}."


RANK_NAMES = {2: "partially covered", 3: "completely covered", 4: "travel advisory", 5: "travel not advised / closed"}


def _rank_name(v) -> str:
    return RANK_NAMES.get(int(v), str(v))


def _reason_phrase(rule: dict) -> str:
    if rule["metric"] == "alert_present":
        return f"{rule['observed_value']} in effect"
    if rule["metric"] == "spc_day1_rank":
        risk = {1: "marginal", 2: "slight", 3: "enhanced", 4: "moderate", 5: "high"}.get(rule["observed_value"])
        if risk:
            return f"a {risk} risk of severe storms in the Storm Prediction Center outlook"
    if rule["unit"] == "rank":
        return f"reported roads at {_rank_name(rule['observed_value'])}"
    return f"{rule['label']} of {_fmt_val(rule['observed_value'], rule['unit'])}"


def build(snap: dict, analogs: list[dict] | None = None) -> Interpretation:
    """`snap` is the serialized snapshot dict produced by app.snapshots."""
    tz = ZoneInfo(snap["facility"]["timezone"])
    p = snap["posture"]
    posture = p["posture"]
    day = datetime.fromisoformat(p["decision_day"]).strftime("%A %b %d")
    conf = snap["confidence"]
    rules = [r for r in snap["rules"] if r["triggered"]]
    ctrl_ids = {rid for h in snap["hazards"].values() for rid in h["controlling_rule_ids"] if h["hazard"] in p["contributing_hazards"]}
    key = [r for r in rules if r["rule_id"] in ctrl_ids] or rules
    key.sort(key=lambda r: (-r["level"], -r["score"]))

    parts = [f"Recommendation for {snap['facility']['name']} for {day}: {posture.replace('_', ' ').title()} "
             f"(OPM: {p['opm_label']})."]
    if not rules:
        parts.append("No NWS alert, forecast, observation or road threshold is crossed for the decision day.")
    alerts = {a.get("event"): a for a in snap.get("alerts", [])}
    for r in key[:3]:
        if r["metric"] == "alert_present":
            for ev in str(r["observed_value"]).split(", "):
                a = alerts.get(ev, {})
                parts.append(f"The NWS has {_article(ev)} {ev} in effect from {_local(a.get('onset') or a.get('effective'), tz)} "
                             f"to {_local(a.get('ends') or a.get('expires'), tz)} (certainty: {a.get('certainty') or 'unknown'}).")
        elif r["unit"].startswith("SPC"):
            sig = snap.get("signals", {}).get(r["metric"], {})
            parts.append(f"The SPC day-1 convective outlook for the facility is {sig.get('detail')} "
                         f"(rule fires at {r['unit'].split('= ')[-1].rstrip(')')} or higher).")
        elif r["unit"] == "rank":
            sig = snap.get("signals", {}).get(r["metric"], {})
            parts.append(f"Iowa DOT reports {sig.get('detail') or 'degraded roads'} as of {_local(r['time_of_peak'], tz)}, "
                         f"at or past our '{_rank_name(r['threshold'])}' cutoff.")
        else:
            when = f" around {_local(r['time_of_peak'], tz)}" if r.get("time_of_peak") else ""
            past = "at" if not r["margin_abs"] else f"{_fmt_val(r['margin_abs'], r['unit'])} past"
            parts.append(f"{r['label']} is {_fmt_val(r['observed_value'], r['unit'])}{when}, {past} the "
                         f"{_fmt_val(r['threshold'], r['unit'])} threshold.")
    for reason in p["reasons"][:2]:
        if rules:
            parts.append(f"Timing: {reason.rstrip('.')}.")
    rd = snap.get("readiness")
    if rd:
        when = f"; decide and announce by {_local(rd['decide_by'], tz)}" if rd.get("decide_by") else ""
        parts.append(f"Readiness is Condition {rd['level'].title()}{when}.")
    weakest = min(conf["factors"], key=lambda f: f["score"])
    parts.append(f"Confidence is {conf['level']} ({conf['score']:.2f}); the weakest factor is {weakest['name']}: "
                 f"{weakest['explanation'].rstrip('.')}.")
    if snap.get("changes"):
        parts.append(snap["changes"][0]["text"])
    parts.append("This is a decision-support recommendation; the final operating-status decision rests with the facility manager.")

    headline = f"{posture.replace('_', ' ').title()} recommended for {day}"
    if key:
        lead = key[0]
        what = lead["observed_value"] if lead["metric"] == "alert_present" else lead["label"]
        headline = f"{posture.replace('_', ' ').title()}: {what}"
    headline = " ".join(headline.split()[:15])

    analog_text = ""
    if analogs:
        a = analogs[0]
        analog_text = (f"Closest past event: {a['name']} ({a['similarity_pct']:.0f}% similar). The rules (backtest, "
                       f"simulated) recommended {a['recommended_posture']} then; outcome: {a['outcome_summary']}")
    return Interpretation(
        headline=headline,
        summary=(f"{posture.replace('_', ' ').title()} is recommended. "
                 + (p["reasons"][0] if p["reasons"] else "No operating-status threshold is crossed for the decision day.")),
        evidence_rule_ids=[r["rule_id"] for r in key[:3]],
        suggested_reasons=[{
            "rule_id": r["rule_id"],
            "text": _reason_phrase(r)[:180],
        } for r in key[:3]],
        uncertainty=f"Confidence is {conf['level']}; {weakest['explanation']}",
        rationale_paragraph=" ".join(parts),
        what_would_change=[c["text"] for c in snap.get("changes", [])],
        watch_next_6h=snap.get("watch_next_6h", []),
        alert_summaries={a["id"]: alert_line(a, tz) for a in snap.get("alerts", [])},
        analog_comparison=analog_text,
    )
