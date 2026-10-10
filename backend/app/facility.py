"""Synthetic facility + roster loading and the 'who is actually in the building' summary."""
from __future__ import annotations

import json
from functools import lru_cache

from adapters.base import Facility
from app.config import settings


@lru_cache
def load_facility() -> Facility:
    return Facility(**json.loads((settings.data_dir / "facility.json").read_text(encoding="utf-8")))


@lru_cache
def load_employees() -> list[dict]:
    return json.loads((settings.data_dir / "employees.json").read_text(encoding="utf-8"))["employees"]


def get_facility(facility_id: str | None = None) -> Facility:
    f = load_facility()
    if facility_id and facility_id != f.id:
        raise KeyError(facility_id)
    return f


def roster_summary(facility: Facility) -> dict:
    """Assigned roster vs. who is expected in the building today.

    The two differ on purpose: details out/in, travel and telework all move
    people, and notifications must follow the person, not the org chart.
    """
    emps = load_employees()
    assigned = [e for e in emps if e["assigned_facility"] == facility.id]
    here = [e for e in emps if e["this_week_location"] == facility.id]
    in_building = [e for e in here if not e["teleworking_today"]]
    detailed_out = [e for e in assigned if e["this_week_location"].startswith("detail:")]
    travel = [e for e in assigned if e["this_week_location"].startswith("travel:")]
    detailed_in = [e for e in here if e["assigned_facility"] != facility.id]
    teleworking = [e for e in here if e["teleworking_today"]]
    by_corridor: dict[str, int] = {}
    for e in in_building:
        by_corridor[e["commute_corridor"]] = by_corridor.get(e["commute_corridor"], 0) + 1
    return {
        "assigned": len(assigned),
        "expected_in_building": len(in_building),
        "detailed_in": len(detailed_in),
        "detailed_out": len(detailed_out),
        "on_travel": len(travel),
        "teleworking_today": len(teleworking),
        "essential_in_building": sum(1 for e in in_building if e["essential"]),
        "accessibility_needs_in_building": sum(1 for e in in_building if e["accessibility_needs"]),
        "commuters_by_corridor": by_corridor,
        "synthetic": True,
    }
