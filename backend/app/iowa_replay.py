"""Committed Ames event catalog, available even before a history database is built.

Saved event summaries and outcomes are retrospective display context. Replay
recommendations are evaluated separately from original, time-gated source data.
"""
from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

FACILITY_ID = "IA-AMES-SC"
EVENT_IDS = (
    "derecho-2020-08-10",
    "wind-2021-12-15",
    "blizzard-2022-12-22",
    "ice-2023-02-22",
    "snow-2024-01-09",
    "advisory-2025-02-05",
    "blizzard-2025-03-05",
)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "history"


@lru_cache(maxsize=1)
def _catalog() -> dict[str, dict]:
    catalog = {}
    for event_id in EVENT_IDS:
        data = json.loads((FIXTURES / f"{event_id}.json").read_text(encoding="utf-8"))
        spec = data["event"]
        if spec["id"] != event_id or spec.get("facility_id", FACILITY_ID) != FACILITY_ID:
            raise ValueError("Iowa replay fixture event/facility mismatch")
        name = spec["name"]
        if event_id == "advisory-2025-02-05":
            name = name.replace("(control case)", "(mild-weather case)")
        catalog[event_id] = {
            **spec, "name": name, "facility_id": FACILITY_ID,
            "timezone": "America/Chicago",
            "verification": data["verification"], "outcome": data["outcome"],
            "backtest": data["backtest"],
        }
    return catalog


def events() -> list[dict]:
    return deepcopy(list(_catalog().values()))


def event(event_id: str) -> dict | None:
    return deepcopy(_catalog().get(event_id))
