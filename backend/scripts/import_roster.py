"""Build backend/data/employees.json from the synthetic roster CSV (data/NADC_synthetic_assignments.csv).

Run from backend/:  python -m scripts.import_roster

Every person in the CSV becomes an employee of the demo facility (IA-AMES-SC). CSV fields
used as-is: id, name, division, job role, schedule (work days + start time), telework
eligibility, required-on-site-during-emergency (= essential), dated details elsewhere and
approved sick leave. The CSV has no home town, commute, contact channels or accessibility
needs, so those are filled with deterministic synthetic values (same input -> same output)
and listed in each record's ``synthetic_fill``. All of it is synthetic demo data.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CSV_PATH = BACKEND.parent / "data" / "NADC_synthetic_assignments.csv"
OUT = BACKEND / "data" / "employees.json"
FACILITY = "IA-AMES-SC"
CSV_FACILITY = "USDA-IA-NADC-CAMPUS"

# home town -> (commute corridor id from facility.json, typical one-way miles), with relative weights
TOWNS = {
    "Ames": ("local", 4, 40), "Gilbert": ("local", 7, 5), "Nevada": ("us30_ames_nevada", 10, 8),
    "Boone": ("us30_ames_boone", 16, 9), "Huxley": ("us69_ames_huxley", 12, 6), "Slater": ("us69_ames_huxley", 15, 4),
    "Story City": ("i35_ames_storycity", 14, 6), "Ankeny": ("i35_ames_dsm", 24, 11), "Des Moines": ("i35_ames_dsm", 32, 11),
}
CHANNELS = [(["sms", "email"], 85), (["email"], 9), (["sms"], 4), (["phone"], 2)]
ACCESSIBILITY = ["Uses wheelchair; needs ramp entrance clear", "Mobility: uses cane; avoid icy lot",
                 "Hearing impaired; text/email only", "Low vision; prefers large-print or audio instructions"]


def _rng(emp_id: str) -> random.Random:
    return random.Random(int(hashlib.sha256(emp_id.encode()).hexdigest()[:16], 16))


def _pick(rng: random.Random, options):
    return rng.choices([o[0] if isinstance(o, tuple) else o for o in options],
                       weights=[o[-1] for o in options])[0]


def parse_schedule(text: str) -> tuple[list[int], str, str, bool]:
    """'Mon-Fri;08:00-16:30' -> ([0..4], '08:00', '16:30', False); rotating Mon-Sun -> all days, rotating=True."""
    parts = text.split(";")
    days = list(range(7)) if parts[0] == "Mon-Sun" else list(range(5))
    start, end = parts[1].split("-")
    return days, start, end, "rotating" in text


def convert(row: dict) -> dict:
    rng = _rng(row["employee_id"])
    town = _pick(rng, [(t, w) for t, (_, _, w) in TOWNS.items()])
    corridor, miles, _ = TOWNS[town]
    workdays, start, end, rotating = parse_schedule(row["work_schedule"])
    essential = row["required_on_site_during_emergency"] == "true"
    e = {
        "id": row["employee_id"], "name": row["employee_name"], "synthetic": True,
        "assigned_facility": FACILITY, "this_week_location": FACILITY,
        "division": row["division"], "job_role": row["job_role"],
        "essential": essential, "essential_role": row["job_role"] if essential else None,
        "emergency_reporting_instruction": row["emergency_reporting_instruction"],
        "telework_eligible": row["telework_eligible"] == "true", "teleworking_today": False,
        "workdays": workdays, "work_start": start, "work_end": end, "rotating_days_off": rotating,
        "work_schedule": row["work_schedule"],
        "home_town": f"{town}, IA", "commute_corridor": corridor,
        "commute_miles": miles + rng.randint(-2, 3) if corridor != "local" else miles,
        "accessibility_needs": rng.choice(ACCESSIBILITY) if rng.random() < 0.04 else None,
        "contact_channels": _pick(rng, CHANNELS),
        "assignments": [], "leave": [],
        "source": {"file": "data/NADC_synthetic_assignments.csv", "employee_id": row["employee_id"],
                   "assignment_type": row["assignment_type"]},
        "synthetic_fill": ["home_town", "commute_corridor", "commute_miles", "accessibility_needs", "contact_channels"],
    }
    if row["facility_id"] != CSV_FACILITY:  # temporary detail away from the facility for a dated window
        e["assignments"].append({"start": row["effective_start"], "end": row["effective_end"],
                                 "this_week_location": "detail:Other USDA facility",
                                 "teleworking_today": row["telework_status"] == "scheduled_telework"})
    elif row["telework_status"] == "scheduled_telework":
        e["assignments"].append({"start": row["effective_start"], "end": row["effective_end"], "teleworking_today": True})
    if row["sick_leave_status"] == "approved" and row["sick_leave_start"]:
        e["leave"].append({"start": row["sick_leave_start"], "end": row["sick_leave_end"] or row["sick_leave_start"],
                           "type": "approved sick leave"})
    return e


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    employees = [convert(r) for r in rows]
    OUT.write_text(json.dumps({
        "_synthetic": "SYNTHETIC roster. Names are fictitious; no real employee data. Imported from "
                      "data/NADC_synthetic_assignments.csv by scripts/import_roster.py; fields listed in "
                      "synthetic_fill are generated, everything else comes from the CSV.",
        "employees": employees,
    }, indent=1), encoding="utf-8")
    print(f"wrote {len(employees)} employees to {OUT}")


if __name__ == "__main__":
    main()
