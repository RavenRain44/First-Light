"""Read-only views of ONE snapshot, exposed to the Strands agent as tools.

Each function returns plain JSON-able data with times already formatted in the
facility's local time zone, so the model can copy values verbatim. The same
outputs are the whitelist the number validator checks the rationale against.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from strands import tool


def _local(ts: str | None, tz: ZoneInfo) -> str | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(tz).strftime("%a %b %d %H:%M %Z")


def _fmt(v: Any, unit: str | None) -> str:
    if v is None:
        return "unavailable"
    if isinstance(v, str):
        return v
    if unit == "in":
        return f"{v:.2f} in"
    if unit in ("mph", "degF"):
        return f"{v:.0f} {'F' if unit == 'degF' else unit}"
    return f"{v:g} {unit or ''}".strip()


def snapshot_summary(snap: dict) -> dict:
    tz = ZoneInfo(snap["facility"]["timezone"])
    p = snap["posture"]
    return {
        "facility": snap["facility"]["name"],
        "facility_is_synthetic": snap["facility"].get("synthetic", True),
        "what_if_location": bool(snap["facility"].get("hypothetical")),
        "time_zone": snap["facility"]["timezone"],
        "as_of_local": _local(snap["as_of"], tz),
        "mode": snap["mode"],
        "recommended_posture": p["posture"],
        "opm_label": p["opm_label"],
        "decision_day": p["decision_day"],
        "posture_reasons": p["reasons"],
        "safety_guidance": p["guidance"],
        "confidence": {"level": snap["confidence"]["level"], "score": snap["confidence"]["score"],
                       "factors": [{"name": f["name"], "score": f["score"], "explanation": f["explanation"]}
                                   for f in snap["confidence"]["factors"]]},
        "hazards": [{"hazard": h["label"], "score": h["score"], "level": h["level_name"], "posture_for_hazard": h["posture"],
                     "peak_local": _local(h.get("time_of_peak"), tz)} for h in snap["hazards"].values()],
        "watch_next_6h_from_rules": snap.get("watch_next_6h", []),
        "people": {k: v for k, v in (snap.get("roster") or {}).items() if k in
                   ("assigned", "expected_in_building", "essential_in_building", "accessibility_needs_in_building")},
        "sources": [{"source": s["label"], "status": s["status"]} for s in snap["sources"]],
    }


def triggered_rules(snap: dict) -> dict:
    tz = ZoneInfo(snap["facility"]["timezone"])
    out = []
    for r in snap["rules"]:
        if not r["triggered"]:
            continue
        out.append({
            "rule_id": r["rule_id"], "hazard": r["hazard"], "what": r["label"],
            "observed": _fmt(r["observed_value"], r["unit"]) if r["metric"] != "alert_present" else r["observed_value"],
            "threshold": "alert in effect" if r["metric"] == "alert_present" else f"{r['operator']} {_fmt(r['threshold'], r['unit'])}",
            "margin": None if r["margin_abs"] is None else _fmt(r["margin_abs"], r["unit"]),
            "margin_percent": r["margin_pct"],
            "peak_local": _local(r.get("time_of_peak"), tz),
            "exceeded_local": [_local(r.get("window_start"), tz), _local(r.get("window_end"), tz)],
            "severity_level": r["posture_effect"],
            "anchor": r["anchor"], "source_url": r["source_url"], "threshold_verified": r["verified"],
        })
    return {"triggered": out, "what_would_change_computed": [c["text"] for c in snap.get("changes", [])]}


def alerts(snap: dict) -> list[dict]:
    tz = ZoneInfo(snap["facility"]["timezone"])
    return [{"id": a["id"], "event": a.get("event"), "severity": a.get("severity"), "certainty": a.get("certainty"),
             "urgency": a.get("urgency"), "onset_local": _local(a.get("onset") or a.get("effective"), tz),
             "ends_local": _local(a.get("ends") or a.get("expires"), tz), "headline": a.get("headline"),
             "description": (a.get("description") or "")[:700]} for a in snap.get("alerts", [])]


def road_conditions(snap: dict) -> dict:
    tz = ZoneInfo(snap["facility"]["timezone"])
    roads = [{"corridor": i["data"]["name"], "worst": i["data"].get("label") or "no report",
              "reported_local": _local(i.get("source_time"), tz)} for i in snap["inputs"] if i["kind"] == "road"]
    rwis = [{"what": i["metric"], "value": i["value"], "unit": i["unit"]} for i in snap["inputs"] if i["id"].startswith("rwis.")]
    status = next((s for s in snap["sources"] if s["adapter"] == "iem_roads"), None)
    return {"corridors": roads, "rwis": rwis, "source_status": status and status["status"],
            "note": status and status.get("detail")}


def analogs(snap: dict) -> list[dict]:
    return [{"name": a["name"], "similarity_pct": round(a["similarity_pct"]), "recommended_then": a["recommended_posture"],
             "what_happened": a["outcome_summary"], "label": a["label"]} for a in snap.get("analogs", [])]


VIEWS: dict[str, Callable[[dict], Any]] = {
    "get_snapshot_summary": snapshot_summary, "get_triggered_rules": triggered_rules, "get_alerts": alerts,
    "get_road_conditions": road_conditions, "get_analogs": analogs,
}


def build_tools(snap: dict, calls: list[str]) -> list:
    """Strands tools bound to this snapshot. ``calls`` records which tools the model used."""

    @tool
    def get_snapshot_summary() -> dict:
        """Recommended posture, OPM label, decision day, timing reasons, confidence and its factors, hazard scores,
        people expected on site, and source status for the current snapshot."""
        calls.append("get_snapshot_summary")
        return snapshot_summary(snap)

    @tool
    def get_triggered_rules() -> dict:
        """Every threshold rule that fired: observed value, threshold, margin, peak time (local), the official
        anchor and whether it is verified; plus the computed 'what would change this' statements."""
        calls.append("get_triggered_rules")
        return triggered_rules(snap)

    @tool
    def get_alerts() -> list:
        """NWS alerts in the snapshot with id, event, severity, certainty, urgency, local onset/end and text."""
        calls.append("get_alerts")
        return alerts(snap)

    @tool
    def get_road_conditions() -> dict:
        """Worst Iowa DOT road condition per commute corridor and RWIS pavement sensor readings."""
        calls.append("get_road_conditions")
        return road_conditions(snap)

    @tool
    def get_analogs() -> list:
        """Closest past events from the backtest, with what the rules recommended then and what happened."""
        calls.append("get_analogs")
        return analogs(snap)

    return [get_snapshot_summary, get_triggered_rules, get_alerts, get_road_conditions, get_analogs]
