"""Synthetic facility + roster loading and the 'who is actually in the building' summary."""
from __future__ import annotations

import json
from datetime import date
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


def employee_on(e: dict, day: str) -> dict:
    """The employee as they stand on ``day`` (YYYY-MM-DD): dated assignments applied, plus
    ``on_leave`` and ``scheduled`` flags. Records without dated fields are returned unchanged."""
    out = dict(e)
    for a in e.get("assignments", []):
        if a["start"] <= day <= a["end"]:
            out.update({k: v for k, v in a.items() if k not in {"start", "end"}})
            break
    if "telework_dates" in e:
        out["teleworking_today"] = day in e["telework_dates"]
    out["on_leave"] = next((lv for lv in e.get("leave", []) if lv["start"] <= day <= lv["end"]), None)
    out["scheduled"] = date.fromisoformat(day).weekday() in e.get("workdays", [0, 1, 2, 3, 4])
    return out


def roster_summary(facility: Facility, day: str | None = None) -> dict:
    """Assigned roster vs. who is expected in the building on ``day`` (default: today's base roster).

    The two differ on purpose: details out/in, travel, telework, leave and days off all move
    people, and notifications must follow the person, not the org chart.
    """
    emps = [employee_on(e, day) for e in load_employees()] if day else load_employees()
    assigned = [e for e in emps if e["assigned_facility"] == facility.id]
    working = [e for e in emps if not e.get("on_leave") and e.get("scheduled", True)]
    here = [e for e in working if e["this_week_location"] == facility.id]
    in_building = [e for e in here if not e["teleworking_today"]]
    detailed_out = [e for e in assigned if e["this_week_location"].startswith("detail:")]
    travel = [e for e in assigned if e["this_week_location"].startswith("travel:")]
    detailed_in = [e for e in here if e["assigned_facility"] != facility.id]
    teleworking = [e for e in here if e["teleworking_today"]]
    by_corridor: dict[str, int] = {}
    for e in in_building:
        by_corridor[e["commute_corridor"]] = by_corridor.get(e["commute_corridor"], 0) + 1
    return {
        "day": day,
        "assigned": len(assigned),
        "expected_in_building": len(in_building),
        "detailed_in": len(detailed_in),
        "detailed_out": len(detailed_out),
        "on_travel": len(travel),
        "teleworking_today": len(teleworking),
        "on_leave": sum(1 for e in emps if e.get("on_leave")),
        "not_scheduled": sum(1 for e in emps if not e.get("scheduled", True) and not e.get("on_leave")),
        "essential_in_building": sum(1 for e in in_building if e["essential"]),
        "accessibility_needs_in_building": sum(1 for e in in_building if e["accessibility_needs"]),
        "commuters_by_corridor": by_corridor,
        "synthetic": True,
    }
