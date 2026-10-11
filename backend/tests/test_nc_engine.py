"""Coastal policy cases verify timing, uncertainty, and native gauge semantics."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from adapters.base import Facility, NormalizedInput, Point, SourceStatus
from app.facility import load_facility
from engine.confidence import NC_EXPECTED
from engine.evaluate import adapters_for, assess
from engine.features import extract
from engine.scoring import load_thresholds


FAC = Facility(id="NC-WILMINGTON-SC", name="Wilmington demonstration", state="NC", lat=34.2257, lon=-77.8750,
               timezone="America/New_York", asos_station="ILM", mos_station="KILM", policy_profile="wilmington",
               warning_ugcs=["NCZ107", "NCC129"], water_gauges=[{"id": "WLON7", "datum": "MLLW"}])
NOW = datetime(2026, 10, 12, 10, tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)


def inp(id_, metric, values, role="forecast", **kw):
    return NormalizedInput(id=id_, kind="series", role=role, metric=metric,
                           unit=kw.pop("unit", "mph"), series=[Point(t=t, v=v) for t, v in values],
                           fetched_at=NOW, source_time=kw.pop("source_time", NOW-timedelta(hours=1)),
                           source="Recorded test source", source_url="https://example.test/source", **kw)


def weather(rain=0):
    hours = [(NOW+timedelta(hours=h), 20) for h in range(73)]
    return [inp("fcst.wind_gust_mph", "wind_gust_mph", hours),
            inp("fcst.wind_speed_mph", "wind_speed_mph", [(t, 12) for t, _ in hours]),
            inp("fcst.temp_f", "temp_f", [(t, 70) for t, _ in hours], unit="degF"),
            inp("fcst.qpf_in", "qpf_in", [(t, rain) for t, _ in hours], unit="in"),
            inp("obs.temp_f", "temp_f", [(NOW, 69)], role="observation", unit="degF", source_time=NOW),
            inp("obs.wind_gust_mph", "wind_gust_mph", [(NOW, 18)], role="observation", source_time=NOW)]


def statuses():
    return [SourceStatus(adapter=k, label=k, status="ok") for k in NC_EXPECTED["live"]]


def alert(event, start, end, sent=NOW-timedelta(hours=2), effective=None):
    data = {"id": f"test:{event}", "event": event, "sent": sent.isoformat(),
            "effective": (effective or sent).isoformat(), "onset": start.isoformat(), "ends": end.isoformat(),
            "certainty": "Likely", "severity": "Severe"}
    return NormalizedInput(id=f"alert:{event}", metric="nws_alert", kind="alert", role="alert", value=event,
                           data=data, source="NWS", source_url="https://api.weather.gov/alerts/test",
                           fetched_at=NOW, source_time=sent)


def gauge(value=7, stage=5.5, datum="MLLW", stage_datum="MLLW", role="forecast", source_time=NOW):
    return inp(f"water.WLON7.{role}", "water_level_ft", [(NOW+timedelta(hours=1) if role == "forecast" else NOW, value)],
               role=role, unit="ft", source_time=source_time,
               data={"station_id": "WLON7", "datum": datum, "flood_stage_datum": stage_datum,
                     "flood_stage_ft": stage, "facility_inundation": False,
                     "scope": "Regional tidal river gauge; not site inundation."})


def test_ames_profile_and_three_hazards_are_preserved():
    ames = load_facility()
    original = load_thresholds()
    assert load_thresholds(facility=ames) is original
    assert load_thresholds(facility=FAC).sha256 != original.sha256
    result = assess(weather(), statuses(), ames, NOW, "live")
    assert set(result.hazards) == {"winter", "wind", "cold"}
    assert "Hurricane Warning" not in [e for r in original.rules for e in (r.events or [])]


def test_wilmington_normal_and_mild_rain_do_not_create_red_or_restriction():
    for rain in (0, 0.01):
        a = assess(weather(rain), statuses(), FAC, NOW, "live")
        assert a.posture.posture == "NORMAL"
        assert a.readiness.level == "WHITE"
        assert a.signals["fcst_rain_24h_in"].value == pytest.approx(rain*24)
        assert not a.hazards["flood"].level
        assert "Iowa" not in a.signals["road_worst_rank"].label
        assert next(f for f in a.confidence.factors if f.name == "completeness").score == 1


def test_heavy_rain_is_monitoring_not_an_inundation_or_closure_prediction():
    a = assess(weather(0.15), statuses(), FAC, NOW, "live")
    assert a.hazards["flood"].level == 1
    assert a.hazards["flood"].planning_only
    assert a.posture.posture == "NORMAL"
    assert a.readiness.level == "YELLOW"
    assert a.signals["fcst_rain_24h_in"].value == pytest.approx(3.6)
    assert a.signals["fcst_rain_24h_in"].window == (NOW, NOW+timedelta(hours=24))


def test_multi_day_winter_amounts_are_not_added_into_a_false_24_hour_total():
    times = [NOW+timedelta(hours=h) for h in (0, 24, 48)]
    snow = inp("fcst.snow_in", "snow_in", [(t, 1) for t in times], unit="in")
    ice = inp("fcst.ice_in", "ice_in", [(t, 0.02) for t in times], unit="in")
    a = assess(weather()+[snow, ice], statuses(), FAC, NOW, "live")
    assert a.signals["fcst_snow_24h_in"].value == 1
    assert a.signals["fcst_ice_24h_in"].value == 0.02
    assert "heaviest 24 h" in a.signals["fcst_snow_24h_in"].label
    assert "planning window" in a.signals["fcst_max_gust_24h_mph"].label
    assert not next(r for r in a.rules if r.rule_id == "winter.fcst_snow_advisory_24h").triggered


def test_hurricane_watch_prepares_without_choosing_closure_or_delay():
    a = assess(weather()+[alert("Hurricane Watch", NOW, NOW+timedelta(hours=48))], statuses(), FAC, NOW, "live")
    assert a.hazards["tropical"].planning_only
    assert a.posture.posture == "NORMAL"
    assert a.readiness.level == "YELLOW"
    assert any("Prepare" in item for item in a.watch_next_6h)


def test_warning_48_hours_ahead_targets_affected_workday_without_claiming_immediacy():
    a = assess(weather()+[alert("Hurricane Warning", NOW+timedelta(hours=52), NOW+timedelta(hours=62))], statuses(), FAC, NOW, "live")
    assert a.posture.decision_day.isoformat() == "2026-10-14"
    assert a.posture.posture == "EARLY_DISMISSAL"
    assert a.readiness.level == "ORANGE"
    assert a.readiness.decide_by.astimezone(ZoneInfo(FAC.timezone)).hour == 8
    assert a.hazards["tropical"].hazard_timing_known


def test_warning_effective_time_is_not_tropical_wind_arrival():
    issued = NOW-timedelta(hours=1)
    a = assess(weather()+[alert("Hurricane Warning", issued, NOW+timedelta(hours=36), effective=issued)], statuses(), FAC, NOW, "live")
    assert not a.hazards["tropical"].hazard_timing_known
    assert a.readiness.level == "ORANGE"
    assert not any("happening now" in reason for reason in a.readiness.reasons)
    assert any("arrival is not established" in reason for reason in a.posture.reasons)
    assert not any("shelter in place" in guidance.lower() for guidance in a.posture.guidance)


def test_current_flash_flood_warning_does_not_give_generic_shelter_or_unsafe_release():
    a = assess(weather()+[alert("Flash Flood Warning", NOW-timedelta(minutes=30), NOW+timedelta(hours=3))], statuses(), FAC, NOW, "live")
    assert a.posture.posture == "CLOSED"
    assert a.readiness.level == "RED"
    assert any("flooded routes" in guidance for guidance in a.posture.guidance)
    assert not any("shelter-in-place" in guidance.lower() for guidance in a.posture.guidance)
    assert a.sufficiency.status == "limited"
    assert not a.sufficiency.supports_all_clear
    assert a.confidence.level != "high"


def test_surge_warning_issue_time_does_not_establish_water_arrival_or_site_inundation():
    issued = NOW-timedelta(hours=1)
    a = assess(weather()+[alert("Storm Surge Warning", issued, NOW+timedelta(hours=36), effective=issued)], statuses(), FAC, NOW, "live")
    assert not a.hazards["coastal"].hazard_timing_known
    assert a.readiness.level == "ORANGE"
    assert not any("happening now" in reason for reason in a.readiness.reasons)
    assert any("do not establish site inundation" in guidance for guidance in a.posture.guidance)


def test_native_gauge_stage_is_regional_monitoring_not_site_flood_depth():
    a = assess(weather()+[gauge()], statuses(), FAC, NOW, "live")
    sig = a.signals["water_above_flood_stage_ft"]
    assert sig.value == 1.5
    assert sig.data["datum"] == "MLLW"
    assert not sig.data["facility_inundation"]
    assert a.hazards["coastal"].planning_only
    assert a.posture.posture == "NORMAL"
    assert a.readiness.level == "YELLOW"


@pytest.mark.parametrize("water", [gauge(datum="NAVD88"), gauge(source_time=NOW+timedelta(minutes=5)),
                                     gauge(role="observation", source_time=NOW-timedelta(hours=4))])
def test_wrong_datum_future_issue_and_stale_gauge_cannot_trigger_stage_rule(water):
    a = assess(weather()+[water], statuses(), FAC, NOW, "live")
    assert not a.signals["water_above_flood_stage_ft"].available
    assert not a.hazards["coastal"].level


def test_source_published_after_asof_is_not_evidence():
    water = gauge()
    water.data["generated_times"] = {(NOW+timedelta(hours=1)).isoformat(): (NOW+timedelta(minutes=1)).isoformat()}
    a = assess(weather()+[water, alert("Flash Flood Warning", NOW, NOW+timedelta(hours=2), sent=NOW+timedelta(minutes=1))], statuses(), FAC, NOW, "replay")
    assert not a.signals["water_above_flood_stage_ft"].available
    assert not a.hazards["flood"].level
    assert not a.alerts


def test_traffic_closure_is_access_hazard_not_flood_or_winter_weather():
    road = NormalizedInput(id="road:bridge", kind="road", role="observation", metric="road_condition_rank", unit="rank", value=5,
                           source="NCDOT", source_url="https://drivenc.gov/", fetched_at=NOW, source_time=NOW,
                           data={"provider": "NCDOT", "corridor": "US74", "name": "US 74 commute", "label": "Road closed", "hazard": "traffic"})
    a = assess(weather()+[road], statuses(), FAC, NOW, "live")
    assert a.hazards["access"].level == 2
    assert a.hazards["flood"].level == a.hazards["winter"].level == 0
    assert a.signals["road_worst_rank"].label == "Worst NCDOT condition on a commute corridor"


def test_native_county_condition_text_is_context_not_a_corridor_rank():
    county = NormalizedInput(id="ncdot.county", kind="road", role="context", metric="road_county_report", value="flooding reported",
                             data={"provider": "NCDOT", "county": "New Hanover"}, source="NCDOT", source_url="https://drivenc.gov/",
                             fetched_at=NOW, source_time=NOW)
    a = assess(weather()+[county], statuses(), FAC, NOW, "live")
    assert not a.signals["road_worst_rank"].available
    assert not a.hazards["access"].level
    assert a.posture.posture == "NORMAL"


def test_missing_inputs_raise_attention_not_a_weather_restriction():
    a = assess([], [], FAC, NOW, "replay")
    assert a.posture.posture == "NORMAL"
    assert a.readiness.level == "YELLOW"
    assert a.sufficiency.status == "insufficient"
    assert not a.sufficiency.supports_all_clear
    assert a.confidence.level == "low"


def test_custom_commutes_change_timing_instead_of_using_global_ames_hours():
    custom = FAC.model_copy(update={"commute_windows": {"am": ["04:00", "06:00"], "pm": ["14:00", "16:00"]}})
    a = assess(weather()+[alert("High Wind Warning", NOW+timedelta(hours=6), NOW+timedelta(hours=7))], statuses(), custom, NOW, "live")
    assert a.posture.posture == "EARLY_DISMISSAL"  # still within working hours
    before_open = NOW.replace(hour=7)  # 03:00 Eastern
    a = assess([alert("High Wind Warning", before_open+timedelta(hours=1), before_open+timedelta(hours=2), sent=before_open-timedelta(hours=2))], [], custom, before_open, "replay")
    assert a.posture.posture == "DELAYED_ARRIVAL"


@pytest.mark.asyncio
async def test_nc_provider_registry_never_queries_iowa_road_or_rwis_sources():
    names = {adapter.name for adapter in await adapters_for(FAC, "live")}
    assert {"ncdot_roads", "nwps_water", "nws_alerts", "nws_grid", "iem_obs"} <= names
    assert not {"iem_roads", "iem_rwis"} & names
