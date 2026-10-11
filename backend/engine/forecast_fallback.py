"""Select usable backup measurements, preserving fresh primary values and provenance."""
from zoneinfo import ZoneInfo

from adapters.base import iso_z, utc
from engine.sufficiency import FORECAST_MAX_AGE_H, RETRIEVAL_MAX_AGE_H, _forecast_check


def usable_forecast(item, as_of, live):
    age = (utc(as_of) - utc(item.fetched_at)).total_seconds() / 3600
    if live and not -0.25 <= age <= RETRIEVAL_MAX_AGE_H:
        return False
    if item.source_time is None:
        return live and bool((item.data or {}).get("live_retrieval_only"))
    issued_age = (utc(as_of) - utc(item.source_time)).total_seconds() / 3600
    return (0 if live else 2) <= issued_age <= FORECAST_MAX_AGE_H


def needs_backup(assessment, inputs):
    check = next(c for c in assessment.sufficiency.checks if c.name == "forecast")
    if check.status != "ok":
        return True
    s = assessment.sufficiency
    live = assessment.mode in ("live", "livecheck")
    # A long temperature series must not hide a missing/short wind or precipitation forecast.
    present = {i.metric for i in inputs if i.role == "forecast" and _forecast_check(
        [i], {}, assessment.as_of, s.window_start, s.window_end, live, ZoneInfo("UTC"))[0].status == "ok"}
    return not {"temp_f", "wind_speed_mph", "wind_gust_mph"} <= present or not present.intersection({"qpf_in", "snow_in", "ice_in"})


def merge_backup(inputs, backup, as_of, live):
    """Backup fills missing hours/metrics; it cannot erase fresh primary hazard evidence."""
    result = list(inputs)
    usable_backup = [i for i in backup if usable_forecast(i, as_of, live)]
    if usable_backup:
        result = [i if not i.id.startswith("fcst.") or usable_forecast(i, as_of, live) else i.model_copy(update={
            "id": f"unused.{i.id}", "role": "context", "note": "Outdated primary forecast excluded; original retained for review."
        }) for i in result]
    for secondary in usable_backup:
        index = next((j for j, i in enumerate(result) if i.id == secondary.id), None)
        if index is None:
            result.append(secondary)
            continue
        primary = result[index]
        points = {utc(p.t): p for p in primary.series or [] if p.v is not None}
        added = [p for p in secondary.series or [] if p.v is not None and utc(p.t) not in points]
        if not added:
            continue
        # Preserve each actual primary point, including a larger hazard than the backup predicts.
        points.update({utc(p.t): p for p in added})
        data = {**(primary.data or {}), "weather_fallback": True,
                "limitations": (secondary.data or {}).get("limitations", []),
                "primary_source": {"source": primary.source, "source_url": primary.source_url,
                                   "source_time": iso_z(primary.source_time) if primary.source_time else None},
                "secondary_source": {"source": secondary.source, "source_url": secondary.source_url,
                                     "source_time": iso_z(secondary.source_time) if secondary.source_time else None,
                                     "fetched_at": iso_z(secondary.fetched_at)},
                "secondary_times": [iso_z(p.t) for p in added],
                "secondary_point_sources": {iso_z(p.t): (secondary.data or {}).get("point_sources", {}).get(iso_z(p.t), {}) for p in added}}
        result[index] = primary.model_copy(update={
            "series": [points[t] for t in sorted(points)], "data": data,
            "source": f"{primary.source}; gaps filled by {secondary.source}",
            "note": "Fresh primary values retained; missing hours filled by the named backup. Provisional.",
        })
    return result
