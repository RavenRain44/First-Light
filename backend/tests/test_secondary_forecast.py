"""Backup feeds, honest units, as-of cutoffs, provenance and provisional decisions."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from adapters import cache
from adapters.base import NormalizedInput, Point, SourceStatus, iso_z, utc
from adapters.secondary_forecast import ArchivedGFSAdapter, OpenMeteoAdapter, gfs_runtime_candidates
from ai import agent, fallback
from app import snapshots
from app.facility import load_facility
from app.routers.core import build_timeseries
from engine import evaluate
from engine.forecast_fallback import merge_backup

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "probe"
AT = datetime(2025, 2, 5, 10, tzinfo=timezone.utc)
FAC = load_facility()


def forecast(metric, value, *, issue=AT - timedelta(hours=4), fetched=AT, backup=False, hours=48):
    return NormalizedInput(id=f"fcst.{metric}", kind="series", role="forecast", metric=metric,
                           unit="degF" if metric == "temp_f" else "mph" if "wind" in metric else "in",
                           series=[Point(t=AT + timedelta(hours=h), v=value) for h in range(hours)],
                           source="Backup" if backup else "Primary", source_url="https://example.test/backup" if backup else "https://example.test/primary",
                           source_time=issue, fetched_at=fetched,
                           data={"weather_fallback": True, "live_retrieval_only": issue is None,
                                 "limitations": ["Ice accumulation is not provided."]} if backup else None)


def status(name, state="ok"):
    return SourceStatus(adapter=name, label=name, status=state)


def inputs():
    return [forecast("temp_f", 65), forecast("wind_speed_mph", 8), forecast("wind_gust_mph", 12),
            forecast("qpf_in", 0), forecast("snow_in", 0), forecast("ice_in", 0)]


@pytest.mark.asyncio
async def test_real_open_meteo_response_preserves_unknown_ice_and_issue_time(monkeypatch):
    data = json.loads((FIXTURES / "open_meteo_forecast.json").read_text())
    at = utc(datetime.fromisoformat(data["hourly"]["time"][12]))
    calls = []
    async def get(url, **kwargs):
        calls.append((url, kwargs))
        return cache.CachedResponse(url, at, data, True)
    monkeypatch.setattr(cache, "get_json", get)
    records, st = await OpenMeteoAdapter().run(FAC, at, "live")
    assert st.status == "ok" and len(calls) == 1
    assert {i.metric for i in records} == {"temp_f", "apparent_temp_f", "wind_speed_mph", "wind_gust_mph", "qpf_in", "snow_in", "pop_pct", "sky_cover_pct"}
    assert all(i.source_time is None and i.data["weather_fallback"] for i in records)
    assert not any(i.metric == "ice_in" or i.role == "alert" for i in records)
    first = next(i for i in records if i.metric == "snow_in").series[0]
    assert first.v == data["hourly"]["snowfall"][12]


@pytest.mark.asyncio
async def test_open_meteo_units_nulls_and_missing_values_are_not_guessed(monkeypatch):
    data = {"utc_offset_seconds": 0, "hourly_units": {"time": "iso8601", "snowfall": "cm", "temperature_2m": "°C", "precipitation": "inch"},
            "hourly": {"time": [iso_z(AT), iso_z(AT + timedelta(hours=1))], "snowfall": [2.54, None], "temperature_2m": [20, 25], "precipitation": [None, None]}}
    async def get(url, **kwargs): return cache.CachedResponse(url, AT, data, True)
    monkeypatch.setattr(cache, "get_json", get)
    records, _ = await OpenMeteoAdapter().run(FAC, AT, "live")
    assert [i.metric for i in records] == ["snow_in"]
    assert records[0].series == [Point(t=AT, v=1)]


@pytest.mark.asyncio
async def test_live_backup_never_fetches_a_forecast_for_replay(monkeypatch):
    async def forbidden(*args, **kwargs): raise AssertionError("Current forecast must not be used in replay")
    monkeypatch.setattr(cache, "get_json", forbidden)
    records, st = await OpenMeteoAdapter(allow_demo_bypass=True).run(FAC, AT, "replay")
    assert records == [] and st.status == "not_applicable"


@pytest.mark.asyncio
async def test_original_gfs_response_units_and_categorical_amounts(monkeypatch):
    data = json.loads((FIXTURES / "iem_mos_gfs_2025-02-05T06.json").read_text())
    data["data"][0].update(q06=5, snw=6)  # These are categories, not inches.
    calls = []
    async def get(url, **kwargs):
        calls.append((url, kwargs))
        return cache.CachedResponse(url, AT, data, True)
    monkeypatch.setattr(cache, "get_json", get)
    records, st = await ArchivedGFSAdapter().run(FAC, AT, "replay")
    assert st.status == "ok" and 1 <= len(calls) <= 3
    assert all(kw["historical"] for _, kw in calls)
    assert {i.metric for i in records} <= {"temp_f", "wind_speed_mph", "pop_pct"}
    assert not {"snow_in", "ice_in", "qpf_in", "wind_gust_mph"}.intersection(i.metric for i in records)
    wind = next(i for i in records if i.metric == "wind_speed_mph")
    assert wind.series[0].v == pytest.approx(8 * 1.150779, abs=0.0001)
    assert all(i.source_time + timedelta(hours=2) <= AT for i in records)
    assert all(i.data["point_sources"][iso_z(p.t)]["source_time"] <= iso_z(AT - timedelta(hours=2)) for i in records for p in i.series)


@pytest.mark.asyncio
async def test_mislabeled_or_future_gfs_run_is_excluded(monkeypatch):
    data = json.loads((FIXTURES / "iem_mos_gfs_2025-02-05T06.json").read_text())
    for row in data["data"]: row["runtime_utc"] = iso_z(AT + timedelta(hours=6))
    async def get(url, **kwargs): return cache.CachedResponse(url, AT, data, True)
    monkeypatch.setattr(cache, "get_json", get)
    records, st = await ArchivedGFSAdapter().run(FAC, AT, "replay")
    assert records == [] and st.status == "empty"


def test_archive_availability_lag_includes_boundary_and_excludes_late_run():
    boundary = datetime(2025, 2, 5, 8, tzinfo=timezone.utc)
    assert gfs_runtime_candidates(boundary)[0].hour == 6
    assert gfs_runtime_candidates(boundary - timedelta(seconds=1))[0].hour == 0


@pytest.mark.asyncio
async def test_stale_prior_archive_runs_are_not_requested_or_merged(monkeypatch):
    calls = []
    async def get(url, **kwargs):
        calls.append(url)
        raise cache.SourceUnavailable("No cached run")
    monkeypatch.setattr(cache, "get_json", get)
    await ArchivedGFSAdapter().run(FAC, AT, "replay")
    assert len(calls) == 2
    assert all("2025-02-05T" in url for url in calls)


def test_backup_fills_holes_without_overwriting_primary_hazards():
    primary = forecast("wind_gust_mph", 80, hours=1)
    secondary = forecast("wind_gust_mph", 10, issue=None, backup=True, hours=3)
    alert = NormalizedInput(id="alert:test", role="alert", kind="alert", metric="nws_alert", value="High Wind Warning",
                            source="NWS", source_url="https://example.test/alert", source_time=AT - timedelta(hours=1), fetched_at=AT)
    result = merge_backup([primary, alert], [secondary], AT, True)
    merged = next(i for i in result if i.id == primary.id)
    assert [p.v for p in merged.series] == [80, 10, 10]
    assert merged.data["secondary_times"] == [iso_z(AT + timedelta(hours=h)) for h in (1, 2)]
    assert merged.data["primary_source"]["source_url"] == primary.source_url
    assert alert in result and primary.series[0].v == 80 and len(primary.series) == 1


def test_outdated_primary_ice_does_not_control_backup_assessment_or_chart():
    stale = forecast("ice_in", 0.5, issue=AT - timedelta(hours=24))
    primary = forecast("temp_f", -20, issue=AT - timedelta(hours=24))
    backup = [forecast("temp_f", 65, issue=None, backup=True), forecast("wind_speed_mph", 8, issue=None, backup=True)]
    result = merge_backup([stale, primary], backup, AT, True)
    assert not any(i.id == "fcst.ice_in" for i in result)
    assert any(i.id == "unused.fcst.ice_in" for i in result)
    a = evaluate.assess(result, [], FAC, AT, "live", employees=[])
    assert a.posture.posture == "NORMAL" and not a.signals["fcst_ice_24h_in"].available
    snap = snapshots.build_snapshot_dict(FAC, a, result, [], "live")
    chart = build_timeseries(snap)
    assert "fcst_ice_in" not in chart["meta"]
    assert all(row.get("fcst_temp_f", 65) == 65 for row in chart["rows"])
    assert chart["meta"]["fcst_temp_f"]["provenance"]["weather_fallback"]


@pytest.mark.parametrize("issue,fetched,live", [(None, AT, False), (AT + timedelta(hours=1), AT, True),
    (AT - timedelta(hours=1), AT, False), (None, AT - timedelta(hours=4), True), (None, AT + timedelta(hours=1), True)])
def test_unavailable_at_selected_time_and_stale_backups_are_rejected(issue, fetched, live):
    secondary = forecast("temp_f", 65, issue=issue, fetched=fetched, backup=True)
    assert merge_backup([], [secondary], AT, live) == []


def test_quiet_backup_prediction_is_provisional_not_an_all_clear_and_ai_reports_it():
    records = [i.model_copy(update={"source_time": None, "data": {"weather_fallback": True, "live_retrieval_only": True}}) for i in inputs() if i.metric != "ice_in"]
    # Even when other sources report successfully, a backup cannot receive high confidence.
    statuses = [status(n) for n in ("nws_grid", "nws_alerts", "iem_obs", "iem_roads", "iem_rwis", "iem_outlook")]
    a = evaluate.assess(records, statuses, FAC, AT, "live", employees=[])
    assert a.posture.posture == "NORMAL" and a.readiness.level == "YELLOW"
    assert a.sufficiency.status == "limited" and a.sufficiency.provisional
    assert a.sufficiency.reason_required and not a.sufficiency.supports_all_clear
    assert a.confidence.level != "high" and a.confidence.score <= 0.65
    snap = snapshots.build_snapshot_dict(FAC, a, records, statuses, "live")
    brief = fallback.build(snap)
    assert "Provisional" in brief.headline and "backup" in brief.summary
    assert agent.sufficiency_problems(brief, snap) == []
    assert agent.sufficiency_problems(brief.model_copy(update={"headline": "Normal day", "summary": "No hazards are expected."}), snap)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["live", "livecheck", "replay", "backtest"])
async def test_gather_uses_only_the_correct_backup_when_primary_forecast_missing(monkeypatch, mode):
    calls = []
    async def adapters(*args): return []
    monkeypatch.setattr(evaluate, "adapters_for", adapters)
    async def live(self, facility, at, run_mode):
        calls.append(("live", run_mode))
        return [forecast("temp_f", 65, issue=None, backup=True)], status("open_meteo")
    async def archived(self, facility, at, run_mode):
        calls.append(("archive", run_mode))
        return [forecast("temp_f", 65, backup=True)], status("iem_gfs")
    monkeypatch.setattr(OpenMeteoAdapter, "run", live)
    monkeypatch.setattr(ArchivedGFSAdapter, "run", archived)
    records, statuses = await evaluate.gather(FAC, AT, mode)
    assert records and len(statuses) == 1
    assert calls == [("live", "live") if mode in ("live", "livecheck") else ("archive", "replay")]


@pytest.mark.asyncio
async def test_complete_primary_forecast_does_not_request_backup(monkeypatch):
    class Primary:
        async def run(self, *args): return inputs(), status("nws_grid")
    async def adapters(*args): return [Primary()]
    async def forbidden(*args): raise AssertionError("Complete primary must not request backup")
    monkeypatch.setattr(evaluate, "adapters_for", adapters)
    monkeypatch.setattr(OpenMeteoAdapter, "run", forbidden)
    records, statuses = await evaluate.gather(FAC, AT, "live")
    assert len(records) == 6 and len(statuses) == 1


@pytest.mark.asyncio
async def test_backup_failure_keeps_primary_assessment_available(monkeypatch):
    async def adapters(*args): return []
    async def fail(url, **kwargs): raise cache.SourceUnavailable("Backup unavailable")
    monkeypatch.setattr(evaluate, "adapters_for", adapters)
    monkeypatch.setattr(cache, "get_json", fail)
    records, statuses = await evaluate.gather(FAC, AT, "live")
    assert records == [] and statuses[0].status == "unavailable"
    assert evaluate.assess(records, statuses, FAC, AT, "live").sufficiency.status == "insufficient"


@pytest.mark.asyncio
async def test_historical_offline_mode_cannot_download_backup(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "cache_dir", tmp_path)
    def forbidden(): raise AssertionError("Historical offline mode must not contact weather APIs")
    monkeypatch.setattr(cache, "_client_get", forbidden)
    token = cache.historical_online.set(False)
    try:
        records, st = await ArchivedGFSAdapter().run(FAC, AT, "replay")
    finally:
        cache.historical_online.reset(token)
    assert not records and st.status == "empty"


@pytest.mark.asyncio
async def test_missing_wind_hours_trigger_backup_despite_complete_temperature(monkeypatch):
    records = inputs()
    records = [i.model_copy(update={"series": i.series[:1]}) if i.metric == "wind_gust_mph" else i for i in records]
    class Primary:
        async def run(self, *args): return records, status("nws_grid")
    async def adapters(*args): return [Primary()]
    async def backup(*args): return [forecast("wind_gust_mph", 10, issue=None, backup=True)], status("open_meteo")
    monkeypatch.setattr(evaluate, "adapters_for", adapters)
    monkeypatch.setattr(OpenMeteoAdapter, "run", backup)
    combined, sources = await evaluate.gather(FAC, AT, "live")
    gust = next(i for i in combined if i.metric == "wind_gust_mph")
    assert len(sources) == 2 and len(gust.series) == 48
    assert gust.series[0].v == 12 and gust.series[1].v == 10
