"""Analog matching: weighted Euclidean nearest neighbour over normalized feature vectors.

Each backtest snapshot (one per event-hour) carries the same feature vector as a
live snapshot. For the current snapshot we find, per past event, the most similar
*active* hour (some hazard level > 0) and return the top events. Historical
recommendations are labelled "simulated by rules (backtest)".
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from datetime import datetime, timedelta

from sqlmodel import select

# feature -> (scale function to 0..1, weight)
FEATURES: dict[str, tuple] = {
    "winter_alert_level": (lambda v: v / 3, 2.0),
    "wind_alert_level": (lambda v: v / 3, 2.0),
    "cold_alert_level": (lambda v: v / 3, 1.0),
    "winter_level": (lambda v: v / 3, 2.0),
    "wind_level": (lambda v: v / 3, 2.0),
    "fcst_ice_in": (lambda v: v / 0.5, 1.5),
    "fcst_snow_in": (lambda v: v / 12, 1.5),
    "max_gust_mph": (lambda v: v / 80, 1.5),
    "road_worst_rank": (lambda v: v / 5, 1.5),
    "min_apparent_f": (lambda v: (32 - v) / 60, 1.0),
    "spc_rank": (lambda v: (v + 1) / 6, 1.0),
    "obs_freezing_hours": (lambda v: v / 3, 1.0),
    "hours_to_peak": (lambda v: (v + 12) / 60, 0.5),
}
COASTAL_FEATURES = {
    "tropical_alert_level": (lambda v: v / 3, 2.0),
    "tropical_level": (lambda v: v / 3, 2.0),
    "flood_alert_level": (lambda v: v / 3, 2.0),
    "flood_level": (lambda v: v / 3, 2.0),
    "coastal_alert_level": (lambda v: v / 3, 2.0),
    "coastal_level": (lambda v: v / 3, 2.0),
    "rain_24h_in": (lambda v: v / 10, 1.5),
}
D_MAX = math.sqrt(sum(w for _, w in FEATURES.values()))
HISTORICAL_MODES = {"replay", "backtest"}


def evidence_analogs(snap: dict) -> list[dict]:
    # Outcome summaries lack verified original publication times. Even an older
    # storm can contain later revisions, so strict replay cannot cite it.
    return [] if snap.get("mode") in HISTORICAL_MODES else snap.get("analogs", [])


def normalize(f: dict) -> dict[str, float]:
    return {k: min(1.0, max(0.0, fn(float(f.get(k, 0.0) or 0.0)))) for k, (fn, _) in FEATURES.items()}


def similarity(a: dict, b: dict) -> float:
    na, nb = normalize(a), normalize(b)
    distance = sum(w * (na[k] - nb[k]) ** 2 for k, (_, w) in FEATURES.items())
    max_distance = D_MAX ** 2
    for key, (scale, weight) in COASTAL_FEATURES.items():
        if a.get(key) or b.get(key):
            av, bv = (min(1, max(0, scale(float(f.get(key) or 0)))) for f in (a,b))
            distance += weight * (av-bv) ** 2
            max_distance += weight
    return max(0.0, 1.0 - math.sqrt(distance / max_distance))


def is_active(f: dict) -> bool:
    return any(f.get(k, 0) > 0 for k in ("winter_level", "wind_level", "winter_alert_level", "wind_alert_level", "cold_alert_level", "tropical_level", "tropical_alert_level", "flood_level", "flood_alert_level", "coastal_level", "coastal_alert_level"))


@lru_cache(maxsize=8)
def _library(facility_id: str = "IA-AMES-SC") -> list[dict]:
    """All backtest event-hours with features, plus each event's outcome. Cached; call reset() after a rebuild."""
    if facility_id == "NC-WILMINGTON-SC":
        from app import nc_replay
        library=[]
        for event_id,data in nc_replay.fixtures().items():
            if data['event']['kind']=='normal-control':continue
            spec=data['event'];at=datetime.fromisoformat(spec['start']);end=datetime.fromisoformat(spec['end'])
            outcome=nc_replay.observed(event_id)
            while at<=end:
                _,_,_,assessment=nc_replay.evaluation(event_id,at)
                library.append({'event_id':event_id,'name':spec['name'],'hazard':spec['hazard'],'as_of':at,
                                'posture':assessment.posture.posture,'features':assessment.features,'outcome':outcome,'partial':True})
                at+=timedelta(hours=1)
        return library
    from app.db import session
    from app.models import HistoryEvent, Snapshot

    with session() as s:
        events = {e.id: e for e in s.exec(select(HistoryEvent)).all()}
        rows = s.exec(select(Snapshot.event_id, Snapshot.as_of, Snapshot.posture, Snapshot.features_json)
                      .where(Snapshot.mode == "backtest", Snapshot.facility_id == facility_id)).all()
    lib = []
    for event_id, as_of, posture, fj in rows:
        e = events.get(event_id)
        if e is None or e.facility_id != facility_id:
            continue
        lib.append({"event_id": event_id, "name": e.name, "hazard": e.hazard, "as_of": as_of, "posture": posture,
                    "features": json.loads(fj), "outcome": json.loads(e.outcome_json)})
    return lib


def reset() -> None:
    _library.cache_clear()


def find_analogs(features: dict, exclude_event: str | None = None, k: int = 3, facility_id: str | None = None, mode: str = "live") -> list[dict]:
    if mode in HISTORICAL_MODES:
        return []
    if not features or not is_active(features):
        return []  # a quiet day matches every event's quiet hours; that comparison means nothing
    try:
        lib = _library() if facility_id in (None,"IA-AMES-SC") else _library(facility_id)
    except Exception:  # noqa: BLE001 - no history DB yet
        return []
    best: dict[str, tuple[float, dict]] = {}
    for row in lib:
        if row["event_id"] == exclude_event or not is_active(row["features"]):
            continue
        sim = similarity(features, row["features"])
        if row["event_id"] not in best or sim > best[row["event_id"]][0]:
            best[row["event_id"]] = (sim, row)
    top = sorted(best.values(), key=lambda x: -x[0])[:k]
    return [{
        "event_id": r["event_id"], "name": r["name"], "hazard": r["hazard"], "similarity_pct": round(sim * 100, 1),
        "matched_as_of": r["as_of"].isoformat() + ("Z" if r["as_of"].tzinfo is None else ""),
        "recommended_posture": r["posture"], "outcome_summary": r["outcome"].get("summary", ""), "outcome": r["outcome"],
        "label": "partial original station archive; simulated by rules" if r.get("partial") else "simulated by rules (backtest)",
        "facility_id": facility_id or "IA-AMES-SC", "partial":r.get("partial",False),
    } for sim, r in top]
