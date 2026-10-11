"""Bounded, ephemeral replay summaries; no snapshot writes or model inference."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from adapters.base import Facility, utc
from app.facility import load_employees, facility_employees
from engine.evaluate import assess, gather

WINDOW_HOURS = 12


async def build_timeline(facility: Facility, as_of: datetime) -> dict:
    as_of = utc(as_of)
    # Retained coastal station events are usable offline, with the same original-source
    # availability gates as their selected report. Outside a retained window, gather
    # other explicitly cached archives; never substitute current weather.
    if facility.id == "NC-WILMINGTON-SC":
        from app import nc_replay
        for event_id, data in nc_replay.fixtures().items():
            start,end=(utc(datetime.fromisoformat(data['event'][key])) for key in ('start','end'))
            if start<=as_of<=end:
                cells=[]
                for h in range(-WINDOW_HOURS,WINDOW_HOURS+1):
                    at=as_of+timedelta(hours=h)
                    if start<=at<=end:
                        _,inputs,statuses,a=nc_replay.evaluation(event_id,at)
                        cells.append({'as_of':at.isoformat(),'posture':a.posture.posture,'readiness':a.readiness.level,
                                      'confidence':a.confidence.level,'coverage':'partial','unavailable_sources':[s.label for s in statuses if s.status=='unavailable'],
                                      'label':'partial original-source reconstruction; simulated by rules'})
                    else:
                        cells.append({'as_of':at.isoformat(),'posture':None,'readiness':None,'confidence':'Low','coverage':'unavailable',
                                      'unavailable_sources':['Outside retained original-source window'],'label':'historical data unavailable'})
                return {'facility_id':facility.id,'as_of':as_of.isoformat(),'timezone':facility.timezone,'selected_index':WINDOW_HOURS,'timeline':cells}
    # Match the employee context used by snapshots.evaluate.
    employees = None if facility.hypothetical else facility_employees(facility)
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
    return {"facility_id":facility.id,"as_of": as_of.isoformat(), "timezone": facility.timezone,
            "selected_index": WINDOW_HOURS, "timeline": timeline}
