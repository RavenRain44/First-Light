"""What actually happened, and whether a decision fit it.

``observed_outcome`` gathers the ground truth for a window around the facility: NWS Local Storm
Reports within 25 miles, the AMW ASOS peak gust and freezing/snow hours, and the worst Iowa DOT
commute corridor. The historical event library (scripts/build_history.py) and the review of past
manager decisions both use it, so a past storm and a past decision are judged the same way.

``grade`` compares a decision's operating status with that outcome. It is deterministic; the AI
review (ai/review.py) explains it in words and may adjust it, and a manager's own review always
takes precedence.
"""
from __future__ import annotations

from datetime import datetime, timezone

from adapters.base import Facility
from adapters.iem_lsr import fetch_lsrs
from adapters.iem_obs import fetch_obhistory, obs_series

ORDER = ["NORMAL", "DELAYED_ARRIVAL", "EARLY_DISMISSAL", "TELEWORK", "CLOSED"]
ROAD_NAMES = {0: "normal", 1: "wet/frost", 2: "partially covered", 3: "completely covered", 4: "travel advisory", 5: "not advised/closed"}
VERDICTS = ("good_call", "too_lenient", "too_strict", "mixed")


async def observed_outcome(facility: Facility, start: datetime, end: datetime, road_ranks: list[int | None] | None = None) -> dict:
    lsrs, lsr_url = await fetch_lsrs(facility, start, end)
    obs_urls = []
    rows, fetched_at = await fetch_obhistory(facility.asos_station, start, end, facility.timezone, urls=obs_urls, network=facility.provider_settings.get("asos_network", f"{facility.state}_ASOS"))
    from adapters.iem_obs import _t
    rows = [r for r in rows if r.get("utc_valid") and start <= _t(r["utc_valid"]) < end]
    s = obs_series(rows)
    peak_gust = max(s.get("peak_gust_mph") or s["wind_gust_mph"], key=lambda x: x[1], default=None)
    station = facility.asos_station or "local airport"
    fz_hours = sum(1 for _, v in s["freezing_precip"] if v >= 1)
    snow_hours = sum(1 for _, v in s["snow_obs"] if v >= 1)
    worst_road = max((r for r in road_ranks or [] if r is not None), default=None)
    by_type: dict[str, int] = {}
    for x in lsrs:
        by_type[x["typetext"]] = by_type.get(x["typetext"], 0) + 1
    wind_mags = [x["magnitude"] for x in lsrs if x.get("magnitude") and "WND" in (x.get("typetext") or "").upper()]
    snow_mags = [x["magnitude"] for x in lsrs if x.get("magnitude") and "SNOW" in (x.get("typetext") or "").upper()]
    ice_mags = [x["magnitude"] for x in lsrs if x.get("magnitude") and "ICE" in (x.get("typetext") or "").upper()]
    parts = []
    if lsrs:
        parts.append(f"{len(lsrs)} storm reports within 25 mi (" + ", ".join(f"{n} {k.lower()}" for k, n in sorted(by_type.items(), key=lambda x: -x[1])[:3]) + ")")
    else:
        parts.append("no storm reports within 25 mi")
    if wind_mags:
        parts.append(f"max reported wind {max(wind_mags):.0f} mph")
    if snow_mags:
        parts.append(f"max reported snow {max(snow_mags):.1f} in")
    if ice_mags:
        parts.append(f"max reported ice {max(ice_mags):.2f} in")
    if peak_gust:
        parts.append(f"{station} peak gust {peak_gust[1]:.0f} mph")
    if fz_hours:
        parts.append(f"{fz_hours} h of freezing precip at {station}")
    if worst_road is not None:
        parts.append(f"worst commute corridor: {ROAD_NAMES[int(worst_road)]}")
    severe = bool(any("TORNADO" in k.upper() for k in by_type) or (wind_mags and max(wind_mags) >= 58) or (peak_gust and peak_gust[1] >= 58) or (worst_road or 0) >= 3
                  or fz_hours >= 2 or (snow_mags and max(snow_mags) >= 6) or (ice_mags and max(ice_mags) >= 0.1))
    expected = int((end - start).total_seconds() / 3600)
    wind_hours = {t for t, v in s["wind_speed_mph"] if v is not None}
    covered = {int((t - start).total_seconds() // 3600) for t, v in s["temp_f"] if v is not None and t in wind_hours and start <= t < end}
    missing_run = longest_gap = 0
    for hour in range(expected):
        missing_run = 0 if hour in covered else missing_run + 1
        longest_gap = max(longest_gap, missing_run)
    complete = len(covered) >= expected * .875 and longest_gap <= 3
    flood_reports = sum(n for name, n in by_type.items() if "FLOOD" in name.upper() or "SURGE" in name.upper())
    if facility.state == "NC":
        severe = severe or flood_reports > 0
        parts.append("Regional reports and airport observations; facility inundation and complete historical road coverage are unverified")
    return {
        "summary": "; ".join(parts) + ".",
        "severe_impact": severe,
        "scope": "Local weather benchmark: tornado report within 25 miles, gust at least 58 mph, road rank at least 3, freezing precipitation at least 2 hours, snow report at least 6 inches or ice at least 0.1 inch. Not facility operating truth.",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "coverage": {"complete": complete, "expected_hours": expected, "observed_hours": len(covered), "largest_gap_hours": longest_gap,
                     "policy": "At least 87.5% of local-day hourly temperature and wind observations and no gap longer than 3 hours; storm-report requests must succeed"},
        "observation_source_urls": obs_urls,
        "observation_fetched_at": fetched_at.isoformat() if fetched_at else None,
        "lsr_count": len(lsrs), "lsr_by_type": by_type, "lsr_source_url": lsr_url,
        "lsrs": lsrs[:40],
        "max_reported_wind_mph": max(wind_mags) if wind_mags else None,
        "max_reported_snow_in": max(snow_mags) if snow_mags else None,
        "max_reported_ice_in": max(ice_mags) if ice_mags else None,
        "amw_peak_gust_mph": round(peak_gust[1], 1) if peak_gust else None,
        "amw_peak_gust_time": peak_gust[0].isoformat() if peak_gust else None,
        "amw_freezing_precip_hours": fz_hours, "amw_snow_hours": snow_hours,
        "station_id": station,
        "station_peak_gust_mph": round(peak_gust[1], 1) if peak_gust else None,
        "station_peak_gust_time": peak_gust[0].isoformat() if peak_gust else None,
        "station_freezing_precip_hours": fz_hours, "station_snow_hours": snow_hours,
        "regional_flood_reports": flood_reports,
        "outcome_sufficient": facility.state != "NC",
        "worst_corridor_rank": worst_road,
    }


def _count(outcome: dict, word: str) -> int:
    return sum(n for k, n in (outcome.get("lsr_by_type") or {}).items() if word in k.upper())


def impact(outcome: dict) -> tuple[str, list[str]]:
    """'major' | 'severe' | 'some' | 'none', with the observations behind it."""
    why: list[str] = []
    tornado, hail = _count(outcome, "TORNADO"), [x.get("magnitude") or 0 for x in outcome.get("lsrs") or [] if "HAIL" in (x.get("typetext") or "").upper()]
    wind = max(outcome.get("max_reported_wind_mph") or 0, outcome.get("station_peak_gust_mph", outcome.get("amw_peak_gust_mph")) or 0)
    snow, ice = outcome.get("max_reported_snow_in") or 0, outcome.get("max_reported_ice_in") or 0
    road = outcome.get("worst_corridor_rank") or 0
    fz = outcome.get("station_freezing_precip_hours", outcome.get("amw_freezing_precip_hours")) or 0
    if tornado:
        why.append(f"{tornado} tornado report{'s' if tornado > 1 else ''} within 25 mi")
    if hail and max(hail) >= 1:
        why.append(f"hail up to {max(hail):g} in")
    if wind >= 58:
        why.append(f"damaging wind up to {wind:.0f} mph")
    if snow >= 6:
        why.append(f"{snow:.1f} in of snow reported")
    if ice >= 0.1 or fz >= 2:
        why.append(f"{fz} h of freezing rain at the airport" if fz >= 2 else f"{ice:.2f} in of ice reported")
    if road >= 3:
        why.append(f"commute roads {ROAD_NAMES[int(road)]}")
    if outcome.get("regional_flood_reports"):
        why.append(f"{outcome['regional_flood_reports']} regional flooding or surge reports; facility inundation unverified")
    major = bool(tornado or wind >= 70 or snow >= 8 or ice >= 0.25 or fz >= 6 or road >= 3)
    if major:
        return "major", why
    if outcome.get("severe_impact") or why:
        return "severe", why
    some = []
    if outcome.get("lsr_count"):
        some.append(f"{outcome['lsr_count']} minor storm report{'s' if outcome['lsr_count'] > 1 else ''}")
    if 40 <= wind < 58:
        some.append(f"gusts to {wind:.0f} mph")
    if fz:
        some.append(f"{fz} h of freezing precip")
    if road >= 1:
        some.append(f"roads {ROAD_NAMES[int(road)]}")
    if some:
        return "some", some
    return "none", ["no storm reports and no significant weather observed"]


def grade(decision_posture: str, outcome: dict, *, warned: bool = False, data_gaps: bool = False) -> dict:
    """Verdict on a decision given what happened. ``warned``: alerts or hazards were active when it was made."""
    level, why = impact(outcome)
    if outcome.get("outcome_sufficient") is False:
        return {"verdict": "mixed", "confidence": 0.3, "impact": level, "assessment_status": "insufficient",
                "reasons": why + ["Outcome coverage is incomplete for coastal hazards and road access; this evidence cannot establish whether the operating decision was correct."]}
    strength = ORDER.index(decision_posture) if decision_posture in ORDER else 0
    if level == "major":
        verdict, conf = ("good_call", 0.85) if strength >= 3 else ("too_lenient", 0.8) if strength <= 1 else ("mixed", 0.6)
    elif level == "severe":
        verdict, conf = ("good_call", 0.8) if strength >= 1 else ("too_lenient", 0.8)
    elif level == "some":
        # Conditions developed but stayed below damaging levels: a strong call is defensible, not clear-cut.
        verdict, conf = ("good_call", 0.7) if strength <= 1 else ("mixed", 0.55)
    else:
        if strength == 0:
            verdict, conf = "good_call", 0.9
        elif strength >= 3:
            verdict, conf = ("mixed", 0.55) if warned else ("too_strict", 0.8)
        else:
            verdict, conf = ("mixed", 0.6) if warned else ("too_strict", 0.65)
        if warned and strength:
            why = why + ["hazardous weather was forecast or under alert when the decision was made, but did not develop"]
    if data_gaps:
        conf -= 0.2
        why = why + ["some observations were unavailable, so this review is less certain"]
    return {"verdict": verdict, "confidence": round(max(0.3, min(0.95, conf)), 2), "impact": level, "reasons": why}
