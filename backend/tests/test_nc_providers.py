"""NC providers retain official provenance, reject hindsight, and protect API keys."""
import gzip
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from adapters import cache
from adapters.base import Facility
from adapters.iem_obs import IEMObsAdapter
from adapters.iem_vtec import IEMVTECAdapter
from adapters.ncdot import NCDOTRoadsAdapter, decode_polyline, get_feed, parse_events
from adapters import ncdot
from adapters.ncdot_cameras import is_snapshot, parse_traffic_cameras
from adapters.nwps import NWPSWaterAdapter, normalize_gauge
from adapters.nws_hurricane import NWSHurricaneLocalAdapter

AT = datetime(2026, 10, 11, 10, 30, tzinfo=timezone.utc)
FAC = Facility(id="NC-TEST", name="Synthetic Wilmington", lat=34.2257, lon=-77.875,
               state="NC", timezone="America/New_York", asos_station="ILM", mos_station="KILM", nws_office="ILM",
               water_gauges=[{"id": "WLON7", "datum": "MLLW", "kind": "tidal_river"}],
               corridors=[{"id": "college", "name": "College Road", "coordinates": [[-77.875,34.2],[-77.875,34.3]]}])


def epoch(t):
    return int(t.timestamp())


def event(**changes):
    return {"ID": 123, "Reported": epoch(AT-timedelta(hours=2)), "LastUpdated": epoch(AT-timedelta(hours=1)),
            "StartDate": epoch(AT-timedelta(hours=2)), "PlannedEndDate": epoch(AT+timedelta(hours=1)),
            "Latitude": 34.2257, "Longitude": -77.875, "RoadwayName": "US 17", "Description": "Road flooding",
            "IsFullClosure": True, **changes}


def hydro_row(valid, generated, value):
    return {"validTime": valid.isoformat(), "generatedTime": generated.isoformat(), "primary": value}


def water_data():
    meta = {"lid": "WLON7", "name": "Cape Fear River at Wilmington (IN MLLW)",
            "flood": {"stageUnits": "ft", "categories": {"minor": {"stage": 5.5}, "moderate": {"stage": 6.75}}}}
    hydro = {
        "observed": {"issuedTime": AT.isoformat(), "primaryUnits": "ft", "data": [
            hydro_row(AT-timedelta(minutes=15), AT-timedelta(minutes=10), 5.0),
            hydro_row(AT+timedelta(minutes=5), AT-timedelta(minutes=1), 5.2),
            hydro_row(AT-timedelta(minutes=5), AT+timedelta(minutes=5), 5.1)]},
        "forecast": {"issuedTime": (AT-timedelta(hours=2)).isoformat(), "primaryUnits": "ft", "data": [
            hydro_row(AT+timedelta(hours=2), AT-timedelta(hours=1), 6.0),
            hydro_row(AT+timedelta(hours=75), AT-timedelta(hours=1), 6.1),
            hydro_row(AT+timedelta(hours=3), AT+timedelta(minutes=5), 6.2),
            hydro_row(AT+timedelta(hours=4), AT-timedelta(hours=1), -9999)]}}
    return meta, hydro


def test_water_separates_roles_filters_unavailable_reports_and_identifies_datum():
    meta, hydro = water_data()
    inputs = normalize_gauge(meta, hydro, FAC.water_gauges[0], AT, AT, "https://api.water.noaa.gov/example")
    observed, forecast = inputs
    assert observed.id == "water.WLON7.observed" and forecast.id == "water.WLON7.forecast"
    assert [(p.t,p.v) for p in observed.series] == [(AT-timedelta(minutes=15),5)]
    assert [(p.t,p.v) for p in forecast.series] == [(AT+timedelta(hours=2),6)]
    assert observed.source_time <= AT and forecast.source_time == AT-timedelta(hours=2)
    assert forecast.data["datum"] == "MLLW" and forecast.data["flood_stage_ft"] == 5.5
    assert forecast.data["facility_inundation"] is False


@pytest.mark.parametrize("change", ["wrong_station", "missing_datum", "configured_datum"])
def test_water_rejects_station_or_datum_mismatches(change):
    meta, hydro = water_data()
    gauge = dict(FAC.water_gauges[0])
    if change == "wrong_station": meta["lid"] = "OTHER"
    if change == "missing_datum": meta["name"] = "River gauge"
    if change == "configured_datum": gauge["datum"] = "NAVD88"
    with pytest.raises(cache.SourceUnavailable):
        normalize_gauge(meta, hydro, gauge, AT, AT, "https://example.test")


def test_water_never_uses_different_units_or_future_forecast_issue():
    meta, hydro = water_data()
    hydro["forecast"]["issuedTime"] = (AT+timedelta(minutes=1)).isoformat()
    assert all(i.role != "forecast" for i in normalize_gauge(meta,hydro,FAC.water_gauges[0],AT,AT,"https://example.test"))
    hydro["observed"]["primaryUnits"] = "m"
    assert normalize_gauge(meta,hydro,FAC.water_gauges[0],AT,AT,"https://example.test") == []


def test_water_never_compares_thresholds_with_different_units():
    meta, hydro = water_data(); meta["flood"]["stageUnits"] = "m"
    inputs = normalize_gauge(meta,hydro,FAC.water_gauges[0],AT,AT,"https://example.test")
    assert all(i.data["flood_stage_ft"] is None and i.data["flood_thresholds_ft"] == {} for i in inputs)


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", [NWPSWaterAdapter(),NCDOTRoadsAdapter(),NWSHurricaneLocalAdapter()])
async def test_live_only_nc_sources_cannot_fetch_in_replay(adapter,monkeypatch):
    async def fail(*args,**kwargs):pytest.fail("Historical replay attempted a current feed")
    monkeypatch.setattr(cache,"get_json",fail)
    inputs,status = await adapter.run(FAC,AT,"replay")
    assert inputs == [] and status.status == "not_applicable" and "archive" in status.detail


def test_roads_only_match_active_known_corridor_reports_and_retain_native_hazard():
    rows = [event(), event(ID=2,LastUpdated=epoch(AT+timedelta(minutes=1))),
            event(ID=3,StartDate=epoch(AT+timedelta(hours=1))),
            event(ID=4,PlannedEndDate=epoch(AT-timedelta(minutes=1))), event(ID=5,Longitude=-79.0)]
    geo = parse_events(rows,FAC,AT)
    assert len(geo["features"]) == 1
    p = geo["features"][0]["properties"]
    assert p["rank"] == 5 and p["full_closure"] and p["hazard"] == "flood"
    assert p["corridors"] == ["college"] and p["provider"] == "NCDOT"
    assert parse_events([],FAC,AT)["features"] == []


def test_a_lane_closure_does_not_mean_the_road_is_closed_or_icy():
    p = parse_events([event(IsFullClosure=False,Description="Crash: one right lane closed")],FAC,AT)["features"][0]["properties"]
    assert p["rank"] == 1 and p["hazard"] == "traffic" and not p["full_closure"]


def test_documented_google_polyline_is_decoded_and_malformed_geometry_rejected():
    assert decode_polyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@') == [[-120.2,38.5],[-120.95,40.7],[-126.453,43.252]]
    assert decode_polyline('~~~~~~~') == []


@pytest.mark.asyncio
async def test_missing_drivenc_key_is_explicit_and_does_not_call_provider(monkeypatch):
    monkeypatch.delenv("NCDOT_API_KEY",raising=False)
    async def fail(*args,**kwargs):pytest.fail("A missing key should not make a request")
    monkeypatch.setattr(cache,"get_json",fail)
    with pytest.raises(cache.SourceUnavailable,match="NCDOT_API_KEY"):
        await get_feed("https://www.drivenc.gov/api/v2/get/event")


@pytest.mark.asyncio
async def test_query_key_is_sent_but_never_persisted_or_returned(monkeypatch,tmp_path):
    marker = "TEST-KEY-MUST-NOT-BE-STORED"
    def responder(request):
        assert request.url.params["key"] == marker
        return httpx.Response(200,json=[{"ID":1}])
    monkeypatch.setattr(cache.settings,"cache_dir",tmp_path)
    monkeypatch.setattr(cache.settings,"demo_mode",False)
    client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    monkeypatch.setattr(cache,"_client",client)
    url = "https://www.drivenc.gov/api/v2/get/event"
    try:
        response = await cache.get_json(url,request_params={"key":marker})
        assert response.url == url and marker not in str(response)
        persisted = gzip.decompress(next(tmp_path.glob("*.json.gz")).read_bytes()).decode()
        assert marker not in persisted and json.loads(persisted)["url"] == url
    finally:await client.aclose()


@pytest.mark.asyncio
async def test_provider_error_cannot_echo_query_key(monkeypatch,tmp_path):
    marker = "TEST-KEY-MUST-NOT-BE-LOGGED"
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(401,text=marker)))
    monkeypatch.setattr(cache,"_client",client)
    monkeypatch.setattr(cache.settings,"cache_dir",tmp_path)
    monkeypatch.setattr(cache.settings,"demo_mode",False)
    try:
        with pytest.raises(cache.SourceUnavailable) as error:
            await cache.get_json("https://www.drivenc.gov/api/v2/get/event",request_params={"key":marker})
        assert marker not in str(error.value)
    finally:await client.aclose()


def test_nc_camera_views_are_nearby_enabled_and_safe_without_fake_capture_times():
    rows = [{"Id":1,"Latitude":FAC.lat,"Longitude":FAC.lon,"Location":"College Road", "Views":[
        {"Id":101,"Url":"https://www.drivenc.gov/map/Cctv/101","Status":"Enabled"},
        {"Id":102,"Url":"https://evil.example/image.jpg","Status":"Enabled"},
        {"Id":103,"Url":"https://www.drivenc.gov/map/Cctv/103","Status":"Disabled"}]}]
    cams = parse_traffic_cameras(rows,FAC,AT)
    assert len(cams) == 1 and len(cams[0]["views"]) == 1
    assert cams[0]["corridor"] == "college" and "capture time" in cams[0]["timestamp_basis"]
    assert "stream_url" not in cams[0]
    for url in ("http://www.drivenc.gov/map/Cctv/1","https://www.drivenc.gov.evil.example/map/Cctv/1",
                "https://www.drivenc.gov/map/Cctv/1?key=secret","https://www.drivenc.gov/map/Cctv/../private",
                "https://127.0.0.1/map/Cctv/1","https://www.drivenc.gov:8000/map/Cctv/1"):
        assert not is_snapshot(url)


@pytest.mark.asyncio
async def test_nc_observations_use_nc_network_and_reject_future_rows(monkeypatch):
    calls=[]
    async def fetch(url,**kwargs):
        calls.append(url)
        if "obhistory" in url:
            assert "network=NC_ASOS" in url and "station=ILM" in url
            return cache.CachedResponse(url,AT,{"data":[
                {"utc_valid":(AT-timedelta(minutes=25)).isoformat(),"tmpf":70,"sknt":10,"raw":"KILM 111005Z AUTO 01010KT 10SM 21/18 A3000 RMK AO2"},
                {"utc_valid":(AT-timedelta(minutes=10)).isoformat(),"tmpf":100,"sknt":50},
                {"utc_valid":(AT+timedelta(minutes=5)).isoformat(),"tmpf":100,"sknt":50}]},False)
        return cache.CachedResponse(url,AT,{"data":[]},False)
    monkeypatch.setattr(cache,"get_json",fetch)
    inputs,status=await IEMObsAdapter().run(FAC,AT,"replay")
    assert status.status == "ok"
    assert all(p.t <= AT-timedelta(minutes=15) for i in inputs for p in (i.series or []))
    assert next(i for i in inputs if i.metric == "temp_f").series[0].v == 70


@pytest.mark.asyncio
async def test_nc_replay_does_not_use_final_vtec_extensions(monkeypatch):
    async def fail(*args,**kwargs):pytest.fail("Final event records must not be requested for NC replay")
    monkeypatch.setattr(cache,"get_json",fail)
    inputs,status=await IEMVTECAdapter(["NCZ107","NCC129"]).run(FAC,AT,"replay")
    assert inputs == [] and status.status == "unavailable"
    assert "Original issued warning" in status.detail


@pytest.mark.asyncio
async def test_original_hurricane_local_statement_checks_body_issue_not_only_index(monkeypatch):
    product_id="11111111-1111-1111-1111-111111111111"
    async def fetch(url,**kwargs):
        if "/types/HLS/" in url:
            data={"@graph":[{"id":product_id,"issuanceTime":(AT-timedelta(hours=1)).isoformat()}]}
        else:data={"productCode":"HLS","issuingOffice":"KILM","issuanceTime":(AT+timedelta(minutes=1)).isoformat(),"productText":"Later statement"}
        return cache.CachedResponse(url,AT,data,False)
    monkeypatch.setattr(cache,"get_json",fetch)
    inputs,status=await NWSHurricaneLocalAdapter().run(FAC,AT,"live")
    assert inputs == [] and status.status == "unavailable"


@pytest.mark.asyncio
async def test_county_report_survives_incident_outage_without_claiming_corridors_are_safe(monkeypatch):
    report_time=AT-timedelta(hours=1)
    fac=FAC.model_copy(update={"provider_settings":{"road_counties":["New Hanover"]}})
    async def fetch(url,**kwargs):
        if url == ncdot.EVENTS_URL:raise cache.SourceUnavailable("Incident feed unavailable")
        rows=[{"County":"New Hanover","Overall for Public Display":"Some standing water reported",
               "US/NC Routes":"Check local restrictions","LastUpdated":epoch(report_time)},
              {"County":"Other","Overall for Public Display":"No hazards","LastUpdated":epoch(AT)},
              {"County":"New Hanover","Overall for Public Display":"Later correction","LastUpdated":epoch(AT+timedelta(minutes=1))}]
        return cache.CachedResponse(url,AT-timedelta(minutes=10),rows,True)
    monkeypatch.setattr(ncdot,"get_feed",fetch)
    monkeypatch.setattr(ncdot,"is_historical",lambda at:False)
    inputs,status=await NCDOTRoadsAdapter().run(fac,AT,"live")
    assert status.status == "ok" and len(inputs) == 1
    assert inputs[0].role == "context" and inputs[0].metric == "road_county_report"
    assert inputs[0].source_time == report_time and inputs[0].fetched_at == AT-timedelta(minutes=10)
    assert all(i.metric != "road_condition_rank" for i in inputs)


@pytest.mark.asyncio
async def test_original_hurricane_statement_is_retained_as_regional_context(monkeypatch):
    product_id="11111111-1111-1111-1111-111111111111"
    issued=AT-timedelta(hours=1)
    async def fetch(url,**kwargs):
        data={"@graph":[{"id":product_id,"issuanceTime":issued.isoformat()}]} if "/types/HLS/" in url else {
            "productCode":"HLS","issuingOffice":"KILM","issuanceTime":issued.isoformat(),"productText":"Original regional forecast text"}
        return cache.CachedResponse(url,AT,data,False)
    monkeypatch.setattr(cache,"get_json",fetch)
    inputs,status=await NWSHurricaneLocalAdapter().run(FAC,AT,"live")
    assert status.status == "ok" and len(inputs) == 1
    assert inputs[0].role == "context" and inputs[0].source_time == issued
    assert "Regional statement" in inputs[0].data["scope"]
