"""Live Check copies the selected site without inheriting its geographic evidence."""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.routers import core, livecheck


def warning():
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[-77.8, 34.2], [-77.9, 34.2], [-77.9, 34.3], [-77.8, 34.2]]]},
            "properties": {"id": "hurricane-test", "event": "Hurricane Warning", "status": "Actual",
                           "affectedZones": ["https://api.weather.gov/zones/forecast/NCZ107"], "areaDesc": "Wilmington"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("facility_id", ["IA-AMES-SC", "NC-WILMINGTON-SC"])
async def test_hypothetical_copy_keeps_site_policy_and_clears_real_site_gauges(monkeypatch, facility_id):
    async def national():
        return [warning()], datetime.now(timezone.utc)

    async def point(*args, **kwargs):
        return {"city": "Wilmington", "state": "NC", "timeZone": "America/New_York", "cwa": "ILM",
                "forecastZone": "NCZ107", "county": "NCC129"}, None

    async def evaluate(facility, as_of, mode):
        assert mode == "livecheck" and facility.hypothetical
        assert not facility.water_gauges and not facility.coastal_gauge_ids and not facility.corridors
        assert facility.provider_settings["origin_facility_id"] == facility_id
        assert facility.warning_ugcs == ["NCZ107", "NCC129"]
        if facility_id == "NC-WILMINGTON-SC":
            assert facility.policy_profile == "wilmington"
        return {"facility": facility.model_dump(), "mode": mode}

    monkeypatch.setattr(livecheck, "_national", national)
    monkeypatch.setattr(livecheck, "resolve_point", point)
    monkeypatch.setattr(livecheck.snapshots, "evaluate", evaluate)
    snap = await livecheck.evaluate(livecheck.LiveCheckIn(facility_id=facility_id, alert_id="hurricane-test"), facility_id)
    assert snap["livecheck"]["base_facility_id"] == facility_id
    assert core._check_snapshot_facility(snap, facility_id) is snap
    other = "IA-AMES-SC" if facility_id == "NC-WILMINGTON-SC" else "NC-WILMINGTON-SC"
    with pytest.raises(HTTPException) as error:
        core._check_snapshot_facility(snap, other)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_handled_live_alerts_use_the_selected_facility_policy(monkeypatch):
    async def national():
        return [warning()], datetime.now(timezone.utc)

    monkeypatch.setattr(livecheck, "_national", national)
    nc = await livecheck.alerts(facility_id="NC-WILMINGTON-SC")
    ia = await livecheck.alerts(facility_id="IA-AMES-SC")
    assert nc["alerts"][0]["handled_hazard"] is True
    assert ia["alerts"][0]["handled_hazard"] is False


@pytest.mark.asyncio
async def test_conflicting_livecheck_sites_rejected_before_fetching_weather(monkeypatch):
    async def unexpected():
        raise AssertionError("Invalid requests must not fetch weather")

    monkeypatch.setattr(livecheck, "_national", unexpected)
    with pytest.raises(HTTPException) as error:
        await livecheck.evaluate(livecheck.LiveCheckIn(facility_id="IA-AMES-SC", alert_id="test"), "NC-WILMINGTON-SC")
    assert error.value.status_code == 422
