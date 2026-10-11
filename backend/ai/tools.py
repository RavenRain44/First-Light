"""Read-only views of ONE snapshot, supplied as grounded inference context.

Each function returns plain JSON-able data with times already formatted in the
facility's local time zone, so the model can copy values verbatim. The same
outputs are the whitelist the number validator checks the rationale against.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from engine import sufficiency


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
    ev = sufficiency.for_snapshot(snap)
    return {
        "facility": snap["facility"]["name"],
        "facility_id": snap["facility"]["id"],
        "facility_state": snap["facility"]["state"],
        "facility_is_synthetic": snap["facility"].get("synthetic", True),
        "what_if_location": bool(snap["facility"].get("hypothetical")),
        "time_zone": snap["facility"]["timezone"],
        "as_of_local": _local(snap["as_of"], tz),
        "mode": snap["mode"],
        "recommended_posture": p["posture"],
        "opm_label": p["opm_label"],
        "decision_day": p["decision_day"],
        "posture_reasons": p["reasons"],
        "readiness": None if not snap.get("readiness") else {
            "level": snap["readiness"]["level"], "meaning": snap["readiness"]["meaning"],
            "reasons": snap["readiness"]["reasons"], "decide_by_local": _local(snap["readiness"].get("decide_by"), tz),
            "recheck_minutes": snap["readiness"]["recheck_minutes"],
            "note": "Readiness is adapted from Cooper's Color Code; a policy aid, not a federal standard."},
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
        # Computed by deterministic rules; the model reports it and never judges evidence adequacy itself.
        "evidence_sufficiency": {k: ev.get(k) for k in ("status", "headline", "reasons", "missing_sources", "provisional", "forecast_sources",
                                                        "stale_sources", "supports_all_clear", "mode_note")},
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
    status = next((s for s in snap["sources"] if s["adapter"] in ("iem_roads", "ncdot_roads")), None)
    return {"corridors": roads, "rwis": rwis, "source_status": status and status["status"],
            "note": status and status.get("detail")}


def water_conditions(snap: dict) -> list[dict]:
    """Source-specific gauge context. Never mix datums or infer site flood depth."""
    tz = ZoneInfo(snap["facility"]["timezone"])
    out = []
    for inp in snap.get("inputs", []):
        if inp.get("metric") != "water_level_ft" or inp.get("id", "").startswith("unused."):
            continue
        data = inp.get("data") or {}
        points = [p for p in inp.get("series") or [] if p.get("v") is not None]
        peak = max(points, key=lambda p: p["v"], default=None)
        out.append({"input_id": inp["id"], "station_id": data.get("station_id") or data.get("gauge_id"),
                    "station_name": data.get("station_name"), "role": inp["role"], "datum": data.get("datum"),
                    "peak_level": _fmt(peak["v"], inp.get("unit")) if peak else "unavailable",
                    "peak_local": _local(peak["t"], tz) if peak else None,
                    "flood_stage": _fmt(data.get("flood_stage_ft"), inp.get("unit")),
                    "source": inp["source"], "source_url": inp["source_url"],
                    "issued_local": _local(inp.get("source_time"), tz),
                    "scope": data.get("scope") or "Gauge conditions only; facility inundation has not been established."})
    return out


def regional_statements(snap: dict) -> list[dict]:
    tz = ZoneInfo(snap["facility"]["timezone"])
    return [{"input_id": inp["id"], "office": (inp.get("data") or {}).get("office"),
             "issued_local": _local(inp.get("source_time"), tz), "source_url": inp["source_url"],
             "scope": (inp.get("data") or {}).get("scope"),
             "original_text_excerpt": ((inp.get("data") or {}).get("text") or "")[:2400]}
            for inp in snap.get("inputs", []) if inp.get("metric") == "hurricane_local_statement"]


def analogs(snap: dict) -> list[dict]:
    from engine.analogs import evidence_analogs
    return [{"name": a["name"], "similarity_pct": round(a["similarity_pct"]), "recommended_then": a["recommended_posture"],
             "what_happened": a["outcome_summary"], "label": a["label"]} for a in evidence_analogs(snap)]


VIEWS: dict[str, Callable[[dict], Any]] = {
    "get_snapshot_summary": snapshot_summary, "get_triggered_rules": triggered_rules, "get_alerts": alerts,
    "get_road_conditions": road_conditions, "get_analogs": analogs,
    "get_water_conditions": water_conditions,
    "get_regional_statements": regional_statements,
}
