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
D_MAX = math.sqrt(sum(w for _, w in FEATURES.values()))


def normalize(f: dict) -> dict[str, float]:
    return {k: min(1.0, max(0.0, fn(float(f.get(k, 0.0) or 0.0)))) for k, (fn, _) in FEATURES.items()}


def similarity(a: dict, b: dict) -> float:
    na, nb = normalize(a), normalize(b)
    d = math.sqrt(sum(w * (na[k] - nb[k]) ** 2 for k, (_, w) in FEATURES.items()))
    return max(0.0, 1.0 - d / D_MAX)


def is_active(f: dict) -> bool:
    return any(f.get(k, 0) > 0 for k in ("winter_level", "wind_level", "winter_alert_level", "wind_alert_level", "cold_alert_level"))


@lru_cache(maxsize=1)
def _library(stamp: int = 0) -> list[dict]:
    """All backtest event-hours with features, plus each event's outcome. Cached; call reset() after a rebuild."""
    from app.db import session
    from app.models import HistoryEvent, Snapshot

    with session() as s:
        events = {e.id: e for e in s.exec(select(HistoryEvent)).all()}
        rows = s.exec(select(Snapshot.event_id, Snapshot.as_of, Snapshot.posture, Snapshot.features_json)
                      .where(Snapshot.mode == "backtest")).all()
    lib = []
    for event_id, as_of, posture, fj in rows:
        e = events.get(event_id)
        if e is None:
            continue
        lib.append({"event_id": event_id, "name": e.name, "hazard": e.hazard, "as_of": as_of, "posture": posture,
                    "features": json.loads(fj), "outcome": json.loads(e.outcome_json)})
    return lib


def reset() -> None:
    _library.cache_clear()


def find_analogs(features: dict, exclude_event: str | None = None, k: int = 3) -> list[dict]:
    if not features or not is_active(features):
        return []  # a quiet day matches every event's quiet hours; that comparison means nothing
    try:
        lib = _library()
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
        "label": "simulated by rules (backtest)",
    } for sim, r in top]
