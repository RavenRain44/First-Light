"""Timing logic: hazard level + when it hits -> OPM-aligned operating posture.

The same hazard maps to different postures depending on when it peaks relative
to facility hours and the commute windows. Ice from 05:00-09:00 is a delay or
telework day; severe wind arriving at 14:00 is an early dismissal.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from adapters.base import Facility, utc
from engine.scoring import LEVEL_NAMES, HazardResult, RuleResult, Thresholds

ORDER = ["NORMAL", "DELAYED_ARRIVAL", "EARLY_DISMISSAL", "TELEWORK", "CLOSED"]
RANK = {p: i for i, p in enumerate(ORDER)}


class PostureResult(BaseModel):
    posture: str
    opm_label: str
    opm_section: str
    decision_day: date
    contributing_hazards: list[str]
    reasons: list[str]
    guidance: list[str]


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


AFTERNOON = time(12, 0)  # after noon, a quiet "today" hands the decision to the next workday


def candidate_days(as_of: datetime, facility: Facility) -> list[date]:
    """Workdays a decision made at ``as_of`` could be about: today (if still before close) and the next workday."""
    local = utc(as_of).astimezone(ZoneInfo(facility.timezone))
    days = []
    if local.weekday() in facility.workdays and local.time() < _t(facility.hours["close"]):
        days.append(local.date())
    d = local.date() + timedelta(days=1)
    while d.weekday() not in facility.workdays:
        d += timedelta(days=1)
    days.append(d)
    return days


def decision_day(as_of: datetime, facility: Facility) -> date:
    """Default decision day when no hazard says otherwise: today in the morning, else the next workday."""
    days = candidate_days(as_of, facility)
    local = utc(as_of).astimezone(ZoneInfo(facility.timezone))
    return days[0] if len(days) > 1 and local.time() < AFTERNOON else days[-1]


def horizon_end(as_of: datetime, facility: Facility, timing: dict) -> datetime:
    """End of the last candidate day's PM commute: forecasts and alerts are judged through this time."""
    return _at(candidate_days(as_of, facility)[-1], timing["pm_commute"][1], ZoneInfo(facility.timezone))


def _at(d: date, hhmm: str, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, _t(hhmm), tzinfo=tz).astimezone(ZoneInfo("UTC"))


def _overlap(a0, a1, b0, b1) -> bool:
    return a0 < b1 and a1 > b0


def _tier_posture(hz: HazardResult, level: int, ctrl: list[RuleResult], as_of: datetime, facility: Facility,
                  timing: dict, D: date) -> tuple[str, str, list[str]]:
    """Posture implied by the rules at one severity level of one hazard, from their combined time window."""
    tz = ZoneInfo(facility.timezone)
    am0, am1 = _at(D, timing["am_commute"][0], tz), _at(D, timing["am_commute"][1], tz)
    pm0, pm1 = _at(D, timing["pm_commute"][0], tz), _at(D, timing["pm_commute"][1], tz)
    open_, close = _at(D, facility.hours["open"], tz), _at(D, facility.hours["close"], tz)
    core_end = _at(D, timing["morning_core_end"], tz)

    starts = [r.window_start for r in ctrl if r.window_start]
    ends = [r.window_end for r in ctrl if r.window_end]
    ws = min(starts) if starts else utc(as_of)
    we = max(ends) if ends else ws + timedelta(hours=6)
    if hz.hazard == "winter":
        we = we + timedelta(hours=int(timing.get("winter_road_recovery_hours", 0)))
    ws, we = utc(ws), utc(we)

    am = _overlap(ws, we, am0, am1)
    late_morning = ws < core_end < we  # still going after the morning core: a delay can't absorb it
    workday = _overlap(ws, we, open_, close)
    pm = _overlap(ws, we, pm0, pm1)
    now = utc(as_of)
    in_progress_at_work = open_ <= now < close and ws <= now < we

    names = ", ".join(sorted({str(r.observed_value) if r.metric == "alert_present" else r.label for r in ctrl}))
    local = lambda dt: dt.astimezone(tz).strftime("%a %H:%M")  # noqa: E731
    when = f"{local(ws)} to {local(we)}{' (incl. road recovery)' if hz.hazard == 'winter' else ''}"
    lvl = LEVEL_NAMES[level]
    guidance: list[str] = []
    convective_now = any(r.metric == "alert_present" and r.triggered and r.window_start and r.window_start <= now
                         and (r.window_end is None or now < r.window_end)
                         and any(k in str(r.observed_value) for k in ("Tornado Warning", "Severe Thunderstorm Warning"))
                         for r in ctrl)
    if convective_now and open_ <= now < close:
        guidance.append("A convective warning is in effect now: shelter in place in the interior storm area; "
                        "do not release employees into the storm. Release only after the warning expires.")

    if level == 1:
        if am:
            return "DELAYED_ARRIVAL", f"{hz.label} is {lvl} ({names}) and overlaps the AM commute ({when})", guidance
        return "NORMAL", f"{hz.label} is {lvl} ({names}) but misses the AM commute ({when}); monitor", guidance
    if level == 2:
        if am and late_morning:
            return "TELEWORK", f"{hz.label} is {lvl} ({names}) through the AM commute and past {timing["morning_core_end"]} ({when})", guidance
        if am:
            return "DELAYED_ARRIVAL", f"{hz.label} is {lvl} ({names}) during the AM commute only ({when})", guidance
        if workday or pm:
            return "EARLY_DISMISSAL", f"{hz.label} is {lvl} ({names}) and arrives during the workday or PM commute ({when})", guidance
        return "NORMAL", f"{hz.label} is {lvl} ({names}) but falls outside facility hours and commutes ({when})", guidance
    # extreme
    if in_progress_at_work:
        guidance.append("Hazard is in progress during work hours: Shelter-In-Place per OPM IV.B.6 if travel is unsafe.")
        return "CLOSED", f"{hz.label} is {lvl} ({names}) and is happening now during work hours ({when})", guidance
    if am or _overlap(ws, we, am1, core_end):
        return "CLOSED", f"{hz.label} is {lvl} ({names}) during the AM commute/morning ({when})", guidance
    if workday or pm:
        return "EARLY_DISMISSAL", f"{hz.label} is {lvl} ({names}) and arrives later in the workday ({when}); release staff before it arrives", guidance
    return "NORMAL", f"{hz.label} is {lvl} ({names}) but outside facility hours on {D:%a %b %d} ({when})", guidance


def hazard_posture(hz: HazardResult, rules: list[RuleResult], as_of: datetime, facility: Facility,
                   timing: dict, D: date) -> tuple[str, str, list[str]]:
    """Return (posture, reason, guidance) for one hazard on workday D.

    Each severity tier is timed separately and the most severe result wins, so an extreme
    hazard arriving at noon cannot hide a significant one already covering the AM commute.
    """
    if hz.level == 0:
        return "NORMAL", f"{hz.label}: no thresholds crossed", []
    trig = [r for r in rules if r.hazard == hz.hazard and r.triggered]
    tiers = []
    for level in sorted({r.level for r in trig}, reverse=True):
        tiers.append(_tier_posture(hz, level, [r for r in trig if r.level == level], as_of, facility, timing, D))
    final = combine([p for p, _, _ in tiers])
    reasons = [why for p, why, _ in tiers if p == final or (final == "TELEWORK" and p != "NORMAL")] or [tiers[0][1]]
    guidance = [g for _, _, gs in tiers for g in gs]
    return final, "; ".join(dict.fromkeys(reasons)), list(dict.fromkeys(guidance))


def combine(postures: list[str]) -> str:
    s = set(postures)
    if "DELAYED_ARRIVAL" in s and "EARLY_DISMISSAL" in s and not s & {"TELEWORK", "CLOSED"}:
        return "TELEWORK"
    return max(postures, key=lambda p: RANK[p]) if postures else "NORMAL"


def _day_result(D, hazards, rules, as_of, facility, th):
    per = {h: hazard_posture(hz, rules, as_of, facility, th.timing, D) for h, hz in hazards.items()}
    return combine([p for p, _, _ in per.values()]), per


def decide(hazards: dict[str, HazardResult], rules: list[RuleResult], as_of: datetime, facility: Facility,
           th: Thresholds) -> PostureResult:
    days = candidate_days(as_of, facility)
    results = {D: _day_result(D, hazards, rules, as_of, facility, th) for D in days}
    local = utc(as_of).astimezone(ZoneInfo(facility.timezone))
    today = days[0] if len(days) > 1 else None
    # Today wins if something affects the rest of today, or if it's still morning; otherwise look at tomorrow.
    if today is not None and (results[today][0] != "NORMAL" or local.time() < AFTERNOON):
        D = today
    else:
        D = days[-1]
    final, per_full = results[D]
    reasons, guidance, per = [], [], {}
    for h, (p, why, g) in per_full.items():
        hz = hazards[h]
        hz.posture, hz.posture_reason = p, why
        per[h] = p
        if hz.level > 0:
            reasons.append(f"{why} -> {p}")
        guidance += g
    if D == today and len(days) > 1:
        nxt, _ = results[days[-1]]
        if nxt != "NORMAL" and RANK[nxt] > RANK[final]:
            reasons.append(f"Looking ahead: the same data points to {nxt} for {days[-1]:%a %b %d}")
    contributing = [h for h, p in per.items() if p != "NORMAL" and (p == final or final == "TELEWORK")]
    if not contributing:
        contributing = [h for h, hz in hazards.items() if hz.level > 0]
    meta = th.postures[final]
    return PostureResult(posture=final, opm_label=meta["opm_label"], opm_section=meta["opm_section"],
                         decision_day=D, contributing_hazards=contributing,
                         reasons=reasons or ["No hazard thresholds crossed for the decision day."],
                         guidance=list(dict.fromkeys(guidance)))
