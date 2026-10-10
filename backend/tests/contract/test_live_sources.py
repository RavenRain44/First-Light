import os

import httpx
import pytest

pytestmark = pytest.mark.contract


@pytest.mark.skipif(not os.getenv("RUN_CONTRACT_TESTS"), reason="set RUN_CONTRACT_TESTS=1")
@pytest.mark.asyncio
async def test_nws_and_nwps_live_contracts():
    headers = {"User-Agent": "FirstLight-contract-test (team@example.invalid)"}
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        point = (await client.get("https://api.weather.gov/points/41.59,-93.62")).json()
        assert point["properties"]["forecastGridData"].startswith(
            "https://api.weather.gov/gridpoints/"
        )
        gauge = (await client.get("https://api.water.noaa.gov/nwps/v1/gauges/DESI4")).json()
        assert isinstance(gauge, dict)
