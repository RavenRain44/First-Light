"""Bounded, ephemeral replay summaries; no snapshot writes or model inference."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from adapters.base import Facility, utc
from app.facility import load_employees
from engine.evaluate import assess, gather

WINDOW_HOURS = 12


async def build_timeline(facility: Facility, as_of: datetime) -> dict:
    as_of = utc(as_of)
    # Match the employee context used by snapshots.evaluate.
    employees = None if facility.hypothetical else load_employees()
    here = [e for e in employees or [] if e["this_week_location"] == facility.id and not e["teleworking_today"]]
    gate = asyncio.Semaphore(3)

    async def point(at: datetime) -> dict:
        async with gate:
            inputs, statuses = await gather(facility, at, "replay")
            a = assess(inputs, statuses, facility, at, "replay", employees=here)
            missing = [s.label for s in statuses if s.status == "unavailable"]
            coverage = "unavailable" if not inputs else "partial" if missing else "complete"
            return {
                "as_of": at.isoformat(),
                "posture": a.posture.posture if inputs else None,
                "readiness": a.readiness.level if inputs else None,
                "confidence": a.confidence.level,
                "coverage": coverage,
                "unavailable_sources": missing,
                "label": "simulated by rules (replay)",
            }

    timeline = await asyncio.gather(*(point(as_of + timedelta(hours=h))
                                      for h in range(-WINDOW_HOURS, WINDOW_HOURS + 1)))
    return {"as_of": as_of.isoformat(), "timezone": facility.timezone,
            "selected_index": WINDOW_HOURS, "timeline": timeline}
