"""NWS Local Storm Reports near a point (IEM). Used as ground truth for outcomes."""
from __future__ import annotations

from datetime import datetime

from adapters import cache
from adapters.base import Facility, is_historical, iso_z

IEM = "https://mesonet.agron.iastate.edu/api/1"


async def fetch_lsrs(facility: Facility, begin: datetime, end: datetime, radius_miles: float = 25) -> tuple[list[dict], str]:
    url = (f"{IEM}/nws/lsrs_by_point.json?lat={facility.lat:.4f}&lon={facility.lon:.4f}"
           f"&radius_miles={radius_miles:g}&begints={iso_z(begin)}&endts={iso_z(end)}")
    r = await cache.get_json(url, historical=is_historical(end))
    rows = r.data.get("data", [])
    keep = ("valid", "type", "typetext", "magnitude", "unit", "city", "county", "remark", "source", "lat", "lon", "qualifier")
    return [{k: x.get(k) for k in keep} for x in rows], url
