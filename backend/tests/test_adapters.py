"""Parser tests against real responses saved in fixtures/probe (Phase 1)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from adapters import cache
from adapters.iem_mos import IEMMOSAdapter, mos_to_hourly, runtime_candidates
from adapters.iem_obs import obs_series
from adapters.iem_roads import match_corridors, road_rank
from adapters.iem_vtec import vtec_row_to_alert
from adapters.nws import NWSGridAdapter, alert_from_feature
from app.facility import load_facility, roster_summary
from engine.normalize import convert, expand_grid_element, parse_duration, parse_valid_time

PROBE = Path(__file__).resolve().parents[1] / "fixtures" / "probe"


def load(name):
    return json.loads((PROBE / name).read_text(encoding="utf-8"))


# --- unit conversion -------------------------------------------------------

def test_unit_conversion():
    assert convert(100.0, "wmoUnit:km_h-1")[0] == pytest.approx(62.1371, rel=1e-4)
    assert convert(100.0, "wmoUnit:km_h-1")[1] == "mph"
    assert convert(0.0, "wmoUnit:degC") == (32.0, "degF")
    assert convert(-40.0, "wmoUnit:degC")[0] == pytest.approx(-40.0)
    assert convert(25.4, "wmoUnit:mm") == (pytest.approx(1.0), "in")
    assert convert(10.0, "wmoUnit:m_s-1")[0] == pytest.approx(22.369, rel=1e-3)
    assert convert(None, "wmoUnit:mm") == (None, "in")
    assert convert(40.0, "wmoUnit:percent") == (40.0, "%")


# --- ISO-8601 interval expansion --------------------------------------------

def test_parse_duration_variants():
    assert parse_duration("PT1H") == timedelta(hours=1)
    assert parse_duration("PT3H") == timedelta(hours=3)
    assert parse_duration("P2D") == timedelta(days=2)
    assert parse_duration("P1DT6H") == timedelta(days=1, hours=6)
    with pytest.raises(ValueError):
        parse_duration("garbage")


def test_parse_valid_time():
    start, dur = parse_valid_time("2026-10-10T12:00:00+00:00/PT3H")
    assert start == datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    assert dur == timedelta(hours=3)


def test_state_element_repeats_each_hour():
    pts = expand_grid_element("windGust", [{"validTime": "2026-10-10T12:00:00+00:00/PT3H", "value": 100.0}], "wmoUnit:km_h-1")
    assert [p[0].hour for p in pts] == [12, 13, 14]
    assert all(p[1] == pytest.approx(62.1371, rel=1e-4) for p in pts)


def test_accumulation_is_split_across_hours():
    pts = expand_grid_element("iceAccumulation", [{"validTime": "2026-10-10T12:00:00+00:00/PT6H", "value": 15.24}], "wmoUnit:mm")
    assert len(pts) == 6
    assert sum(v for _, v in pts) == pytest.approx(0.6)  # 15.24 mm = 0.6 in total, preserved


def test_real_gridpoints_fixture_expands_hourly():
    g = load("nws_gridpoints.json")["properties"]
    for el in ("windGust", "temperature", "iceAccumulation", "snowfallAmount", "probabilityOfPrecipitation"):
        pts = expand_grid_element(el, g[el]["values"], g[el]["uom"])
        times = [t for t, _ in pts]
        assert times == sorted(times)
        assert all((b - a) == timedelta(hours=1) for a, b in zip(times, times[1:])), el


# --- NWS alerts -------------------------------------------------------------

def test_alert_parser_on_real_national_alerts():
    feats = load("nws_alerts_national.json")["features"]
    assert feats
    a = alert_from_feature(feats[0])
    for k in ("id", "event", "severity", "certainty", "urgency", "onset", "ends", "expires", "sent"):
        assert k in a


# --- IEM ---------------------------------------------------------------------

def test_obs_series_from_real_obhistory():
    rows = load("iem_obhistory_AMW.json")["data"]
    s = obs_series(rows)
    assert len(s["temp_f"]) >= 20  # one per hour
    # 2023-02-22 had freezing rain at AMW (wxcodes -FZRA)
    assert any(v == 1.0 for _, v in s["freezing_precip"])
    # gust converted from knots: 25 kt ~ 28.8 mph appears
    assert max(v for _, v in s["wind_gust_mph"]) > 25


def test_vtec_archive_row_maps_to_alert():
    rows = load("iem_county_zone_2023-02-22T14.json")["data"]
    row = next(r for r in rows if r["ugc"] == "IAZ048")
    a = vtec_row_to_alert(row)
    assert a["event"] == "Ice Storm Warning"
    assert a["severity"] == "Extreme"  # warning of an extreme phenomenon
    assert "severity" in a["inferred_fields"]


def test_mos_hourly_units():
    rows = load("iem_mos_nbs_2023-02-22T01.json")["data"]
    h = mos_to_hourly(rows)
    first = rows[0]
    t0 = datetime.fromisoformat(first["ftime_utc"]).replace(tzinfo=timezone.utc)
    gust = dict(h["wind_gust_mph"])
    assert gust[t0] == pytest.approx(first["gst"] * 1.150779, abs=0.1)
    # total ice over the run equals sum of I06 (hundredths of inch)
    assert sum(v for _, v in h["ice_in"]) == pytest.approx(sum((r["i06"] or 0) for r in rows) / 100, abs=0.01)


def test_mos_sky_cover_preserves_percent_and_missing_data():
    rows = load("iem_mos_nbs_2023-02-22T01.json")["data"]
    first = rows[0]
    t0 = datetime.fromisoformat(first["ftime_utc"]).replace(tzinfo=timezone.utc)
    sky = dict(mos_to_hourly(rows)["sky_cover_pct"])
    assert sky[t0] == first["sky"]
    assert sky[t0 - timedelta(hours=1)] == first["sky"]
    assert sky[t0 + timedelta(hours=1)] == first["sky"]
    assert mos_to_hourly([{"ftime_utc": first["ftime_utc"], "sky": None}])["sky_cover_pct"] == []
    assert dict(mos_to_hourly([{"ftime_utc": first["ftime_utc"], "sky": 0}])["sky_cover_pct"])[t0] == 0


@pytest.mark.asyncio
async def test_live_grid_sky_is_context_from_the_existing_response(monkeypatch):
    grid = load("nws_gridpoints.json")
    at = datetime.fromisoformat(grid["properties"]["skyCover"]["values"][0]["validTime"].split("/")[0])
    calls = []

    async def fake_get(url, **kwargs):
        calls.append(url)
        data = {"properties": {"gridId": "DMX", "gridX": 73, "gridY": 56, "forecastGridData": "https://example.test/grid",
                               "forecastZone": "https://example.test/IAZ048", "county": "https://example.test/IAC169"}} if "/points/" in url else grid
        return cache.CachedResponse(url=url, fetched_at=at, data=data, from_cache=True)

    monkeypatch.setattr(cache, "get_json", fake_get)
    inputs, status = await NWSGridAdapter().run(load_facility(), at, "live")
    assert status.status == "ok"
    sky = next(i for i in inputs if i.id == "fcst.sky_cover_pct")
    assert sky.role == "context" and sky.unit == "%"
    assert sky.series and sky.series[0].v == grid["properties"]["skyCover"]["values"][0]["value"]
    assert len(calls) == 2  # point metadata and the forecast already used by the engine
    assert next(i for i in inputs if i.id == "fcst.wind_gust_mph").role == "forecast"


@pytest.mark.asyncio
async def test_archived_sky_uses_available_nbs_runs_as_context(monkeypatch):
    payload = load("iem_mos_nbs_2023-02-22T01.json")
    at = datetime(2023, 2, 22, 8, 30, tzinfo=timezone.utc)
    calls = []

    async def fake_get(url, **kwargs):
        calls.append(url)
        return cache.CachedResponse(url=url, fetched_at=at, data=payload, from_cache=True)

    monkeypatch.setattr(cache, "get_json", fake_get)
    inputs, status = await IEMMOSAdapter().run(load_facility(), at, "replay")
    assert status.status == "ok"
    sky = next(i for i in inputs if i.id == "fcst.sky_cover_pct")
    assert sky.role == "context" and sky.unit == "%" and sky.series
    assert sky.source_time == runtime_candidates(at)[0]
    assert all(0 <= p.v <= 100 for p in sky.series)
    assert len(calls) == 2  # the existing newest/previous-run merge; no extra sky request


def test_runtime_candidates_respect_availability_lag():
    c = runtime_candidates(datetime(2023, 2, 22, 8, 30, tzinfo=timezone.utc))
    assert c[0] == datetime(2023, 2, 22, 1, tzinfo=timezone.utc)  # 07Z run not yet available at 08:30Z
    assert c[1] == datetime(2023, 2, 21, 19, tzinfo=timezone.utc)


def test_road_rank_ordering():
    assert road_rank("Normal") == 0
    assert road_rank("Wet") == 1
    assert road_rank("PC Frost") == 1
    assert road_rank("PC Ice") == 2
    assert road_rank("CC Snow") == 3
    assert road_rank("Travel Advisory") == 4
    assert road_rank("Closed") == 5
    assert road_rank(None) is None


def test_corridor_matching_on_real_segments():
    fac = load_facility()
    gj = load("iem_roadcond_2023-02-22T20.geojson")
    hits = {c.id: 0 for c in fac.corridors}
    for f in gj["features"]:
        for cid in match_corridors(f["geometry"], fac.corridors):
            hits[cid] += 1
    assert all(n > 0 for n in hits.values()), hits


def test_roster_differs_from_building_population():
    fac = load_facility()
    s = roster_summary(fac, "2026-10-12")  # Monday: CSV details and scheduled telework are active
    assert s["assigned"] == 270 and s["assigned"] != s["expected_in_building"]
    assert s["detailed_out"] > 0 and s["teleworking_today"] > 0
    assert roster_summary(fac, "2026-10-13")["on_leave"] > 0      # approved sick leave from the CSV
    assert roster_summary(fac, "2026-10-11")["not_scheduled"] > 0  # Sunday: only rotating schedules work


def test_hourly_obs_use_routine_metar_like_weather_gov():
    """Real AMW reports from 2026-10-10 20Z: 5-minute obs carry no temperature; the :53 routine METAR does."""
    rows = [
        {"utc_valid": "2026-10-10T20:50Z", "tmpf": None, "sknt": 17.0, "gust": 22.0, "peak_wind_gust": None, "feel": None,
         "raw": "KAMW 102050Z AUTO 17017G22KT 10SM CLR 29/13 A2984 RMK T02900130 MADISHF"},
        {"utc_valid": "2026-10-10T20:53Z", "tmpf": 85.0, "sknt": 13.0, "gust": 24.0, "peak_wind_gust": None, "feel": 84.0,
         "raw": "KAMW 102053Z AUTO 17013G24KT 10SM CLR 29/13 A2984 RMK AO2 SLP094 T02940133"},
        {"utc_valid": "2026-10-10T20:55Z", "tmpf": None, "sknt": 16.0, "gust": 26.0, "peak_wind_gust": None, "feel": None,
         "raw": "KAMW 102055Z AUTO 16016G26KT 10SM CLR 29/13 A2984 RMK T02900130 MADISHF"},
    ]
    s = {k: dict(v) for k, v in obs_series(rows).items()}
    hr = datetime(2026, 10, 10, 20, tzinfo=timezone.utc)
    assert s["temp_f"][hr] == pytest.approx(84.9)                # T-group 29.4 C from the routine report
    assert s["wind_speed_mph"][hr] == pytest.approx(13 * 1.150779)  # routine report, not the hour's max
    assert s["wind_gust_mph"][hr] == pytest.approx(24 * 1.150779)
    assert s["peak_gust_mph"][hr] == pytest.approx(26 * 1.150779)   # highest gust in any report, for thresholds
