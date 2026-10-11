"""Experimental, qualitative risk of each operating action for one weather snapshot.

Compares Normal operations, Delayed arrival, Telework / unscheduled leave and Closure as separate
scenarios. Ratings are qualitative on purpose: the app has no injury, crash or financial-loss data for
this facility, so it reports no probabilities or dollar figures. Missing forecasts, road conditions or
facility evidence are never treated as evidence of safety: a rating that would be "lower" becomes
"unknown" when key inputs are missing. Read-only: nothing here records a decision, changes the
suggestion or notifies anyone.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from engine.posture import _at, _overlap

# Each key input and the adapters that can supply it (live NWS, or the IEM archives used for past days).
KEY_SOURCES = {"Forecast": ("nws_grid", "iem_mos"), "Weather alerts": ("nws_alerts", "iem_vtec"), "Road conditions": ("iem_roads",)}
ALWAYS_MISSING = ["Facility status (power, heating, parking-lot and ramp condition) is not reported to the app.",
                  "Actual staffing levels and who can reach the site are not known until the day.",
                  "No injury, crash or financial-loss data for this facility: action-specific risk cannot be quantified."]
DELAY_HOURS = 2  # typical delayed-arrival offset after opening


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _periods(day: date, facility: dict, timing: dict) -> dict[str, tuple[datetime, datetime]]:
    tz = ZoneInfo(facility["timezone"])
    return {"am_commute": (_at(day, timing["am_commute"][0], tz), _at(day, timing["am_commute"][1], tz)),
            # The commute window of a delayed arrival, through the end of the morning.
            "late_morning": (_at(day, facility["hours"]["open"], tz) + timedelta(hours=DELAY_HOURS), _at(day, timing["morning_core_end"], tz)),
            "afternoon": (_at(day, timing["morning_core_end"], tz), _at(day, facility["hours"]["close"], tz)),
            "pm_commute": (_at(day, timing["pm_commute"][0], tz), _at(day, timing["pm_commute"][1], tz))}


def hazard_timing(snapshot: dict, timing: dict) -> list[dict]:
    """Active hazards and which parts of the decision day they overlap."""
    day = date.fromisoformat(str(snapshot["posture"]["decision_day"]))
    periods = _periods(day, snapshot["facility"], timing)
    out = []
    for h in snapshot.get("hazards", {}).values():
        if not h.get("level"):
            continue
        a, b = _dt(h.get("window_start")), _dt(h.get("window_end"))
        hits = [p for p, (s, e) in periods.items() if a and b and _overlap(a, b, s, e)]
        out.append({"hazard": h["label"], "level": h["level"], "level_name": h["level_name"],
                    "overlaps": hits, "timing_known": bool(a and b)})
    return out


def missing_inputs(snapshot: dict) -> list[str]:
    status = {s["adapter"]: s for s in snapshot.get("sources", [])}
    out = []
    for label, adapters in KEY_SOURCES.items():
        found = [status[a] for a in adapters if a in status]
        if any(s["status"] == "ok" for s in found):
            continue
        s = found[0] if found else None
        if not s:
            out.append(f"{label}: not supplied for this snapshot.")
        elif s["status"] == "empty":
            out.append(f"{label}: no reports returned. Not evidence of safe conditions.")
        else:
            out.append(f"{label}: {s['status']}{' (' + s['detail'] + ')' if s.get('detail') else ''}. Not evidence of safe conditions.")
    return out


def _level(hazards: list[dict], periods: set[str]) -> int:
    """Worst hazard level touching any of these periods; hazards with unknown timing count everywhere."""
    return max((h["level"] for h in hazards if not h["timing_known"] or periods & set(h["overlaps"])), default=0)


def _exposure(level: int, missing: bool) -> str:
    rating = "lower" if level == 0 else "moderate" if level == 1 else "elevated"
    return "unknown" if rating == "lower" and missing else rating


def assess_actions(snapshot: dict, employees: list[dict], timing: dict) -> dict:
    hazards = hazard_timing(snapshot, timing)
    missing = missing_inputs(snapshot)
    roster = snapshot.get("roster") or {}
    expected = roster.get("expected_in_building", sum(e.get("assigned_facility") == snapshot["facility"]["id"] for e in employees))
    essential = roster.get("essential_in_building", sum(bool(e.get("essential")) for e in employees))
    remote_ok = sum(bool(e.get("telework_eligible")) and not e.get("essential") for e in employees)
    no_remote = sum(not e.get("telework_eligible") and not e.get("essential") for e in employees)
    road_rank = (snapshot.get("features") or {}).get("road_worst_rank") or 0
    lvl_all = _level(hazards, {"am_commute", "late_morning", "afternoon", "pm_commute"})
    # A delayed arrival avoids the normal AM commute but not hazards later in the day.
    lvl_delayed = _level(hazards, {"late_morning", "afternoon", "pm_commute"})
    if road_rank >= 3:  # roads already reported covered/impassable are a commute hazard of their own
        lvl_all, lvl_delayed = max(lvl_all, 2), max(lvl_delayed, 2)

    def scenario(action, label, exposure_level, people, travel, costs, open_risks):
        return {"action": action, "label": label, "weather_exposure": _exposure(exposure_level, bool(missing)),
                "people_travelling": people, "who_travels": travel, "costs_of_acting": costs, "risks_if_conditions_worsen": open_risks}

    open_risks = []
    if lvl_all:
        open_risks = ["Hazardous commuting for staff on the affected corridors",
                      "Injury exposure on untreated walkways (the north ramp is unheated and ices first)",
                      "Staff may be stranded on site if conditions worsen during the day",
                      "Delayed protective action if the hazard arrives earlier than forecast"]
    elif missing:
        open_risks = ["Cannot rule out hazardous commuting: key inputs are missing"]
    scenarios = [
        scenario("NORMAL", "Normal operations", lvl_all, expected, "All expected staff commute at normal times",
                 ["None from the decision itself"], open_risks),
        scenario("DELAYED_ARRIVAL", "Delayed arrival", lvl_delayed, expected,
                 f"All expected staff commute about {DELAY_HOURS} hours later than usual",
                 ["Lost morning productivity and services", "Some unscheduled leave"],
                 open_risks if lvl_delayed else ["Late-arriving staff may still meet lingering road hazards"] if lvl_all else []),
        scenario("TELEWORK", "Telework / unscheduled leave", min(lvl_all, 1), essential,
                 f"Only essential staff ({essential}) are expected to report",
                 [f"{no_remote} staff have no telework option and must take leave", "In-person services and lab work paused",
                  f"{remote_ok} telework-eligible staff work remotely"],
                 ["Essential staff still commute and need site access"] if lvl_all else []),
        scenario("CLOSED", "Closure", min(lvl_all, 1), essential, f"Only essential staff ({essential}) report under the closure plan",
                 ["All public services stop for the day", "Largest leave and productivity cost",
                  "Essential operations (animal care, facilities) still have to be staffed"],
                 ["Essential staff still commute and need site access"] if lvl_all else []),
    ]
    return {"experimental": True, "quantitative": False,
            "label": "Experimental, qualitative assessment. Separate from the recorded decision; it does not change the suggestion or notify anyone.",
            "quantitative_note": "Action-specific risk estimates (injury probabilities, financial losses) need data this app does not have.",
            "decision_day": str(snapshot["posture"]["decision_day"]), "hazards": hazards, "road_worst_rank": road_rank,
            "staff": {"expected_in_building": expected, "essential": essential, "telework_eligible": remote_ok, "no_remote_option": no_remote},
            "missing_inputs": missing + ALWAYS_MISSING, "scenarios": scenarios}
