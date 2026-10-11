"""Evidence sufficiency: is there enough usable, fresh weather evidence to support the assessment?

Separate from the operating posture (what the rules recommend), confidence (how much the sources agree)
and readiness (how urgently to decide). Missing evidence never chooses a posture: the rules' NORMAL is a
fallback, so when evidence is insufficient the dashboard must not present it as an all-clear.

Policy (deterministic; POLICY_VERSION is stored with every result):

1. Core evidence is a forecast that covers the decision window, from ``as_of`` through the end of the
   decision day's PM commute. Live and livecheck use the NWS gridded forecast; replay and backtest use the
   archived NBS forecast. A forecast counts when
   - it was issued no more than FORECAST_MAX_AGE_H before ``as_of`` (never after it),
   - at least COVERAGE_MIN of the window's hours have a forecast value (within 90 minutes, so 3-hourly
     archive data counts), and
   - live only: it was retrieved no more than RETRIEVAL_MAX_AGE_H before ``as_of``. The HTTP cache keeps
     the original retrieval time, so a stale cached copy served after a failed retry still reads as old.
2. Supporting evidence is a checked alert feed and recent observations (OBS_MAX_AGE_H). A feed that was
   checked and returned no alerts is recorded as "checked: none in effect", which is different from an
   unavailable feed, but on its own it never establishes safe weather.
3. Road, RWIS and SPC outlook data are optional context. Iowa DOT road reporting is seasonal and
   Iowa-only; "not applicable" or empty optional sources never block an assessment.
4. Status:
   - sufficient: core forecast plus both kinds of supporting evidence.
   - limited: core forecast with a supporting gap, or no core forecast but credible positive hazard
     evidence. The hazard recommendation stands, because missing sources can hide a worse hazard but
     never a milder one.
   - insufficient: no usable core forecast and no credible hazard evidence. NORMAL is then only the
     fallback; a manager may still record a decision, with an explicit reason.
5. Evidence is judged against ``as_of``. In replay or backtest that is the replayed moment, never the
   current time, and the result is labelled as historical. In demo mode it is the cached live moment.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from adapters.base import NormalizedInput, SourceStatus, utc
from engine.posture import PostureResult, _at
from engine.scoring import HazardResult, RuleResult

POLICY_VERSION = "evidence-sufficiency-v1"
FORECAST_MAX_AGE_H = 12
RETRIEVAL_MAX_AGE_H = 3
OBS_MAX_AGE_H = 2
COVERAGE_MIN = 0.8
CORE_FORECAST = {"temp_f", "apparent_temp_f", "wind_gust_mph", "wind_speed_mph", "qpf_in", "snow_in", "ice_in"}
FORECAST_ADAPTERS = {"live": "nws_grid", "replay": "iem_mos"}
ALERT_ADAPTERS = {"live": "nws_alerts", "replay": "iem_vtec"}
OPTIONAL = {"iem_roads", "iem_rwis", "iem_outlook"}

Status = Literal["sufficient", "limited", "insufficient"]


class EvidenceCheck(BaseModel):
    name: str  # forecast | alerts | observations | <optional adapter>
    label: str
    status: Literal["ok", "checked_none", "missing", "stale", "partial", "not_applicable", "optional_missing"]
    required: bool
    detail: str


class Sufficiency(BaseModel):
    status: Status
    headline: str
    reasons: list[str]
    missing_sources: list[str]
    stale_sources: list[str]
    checks: list[EvidenceCheck]
    supports_all_clear: bool  # a NORMAL posture may be read as a supported all-clear
    reason_required: bool  # recording a decision needs an explicit manager reason
    hazard_evidence: list[str]  # credible positive hazard evidence kept despite gaps
    window_start: datetime
    window_end: datetime
    forecast_coverage: float | None
    evaluated_as_of: datetime
    mode: str
    mode_note: str
    policy_version: str = POLICY_VERSION


def _family(mode: str) -> str:
    return "live" if mode in ("live", "livecheck") else "replay"


def _hours(a: datetime, b: datetime) -> float:
    return (utc(a) - utc(b)).total_seconds() / 3600


def _fmt(t: datetime, tz: ZoneInfo) -> str:
    return utc(t).astimezone(tz).strftime("%a %H:%M %Z")


def decision_window(as_of: datetime, posture: PostureResult, timing: dict, tz: ZoneInfo) -> tuple[datetime, datetime]:
    end = _at(posture.decision_day, timing["pm_commute"][1], tz)
    return utc(as_of), max(utc(as_of), end)


def _retrieval_stale(i: NormalizedInput, as_of: datetime, live: bool) -> bool:
    return live and _hours(as_of, i.fetched_at) > RETRIEVAL_MAX_AGE_H


def _forecast_check(inputs, statuses, as_of, start, end, live, tz) -> tuple[EvidenceCheck, float | None]:
    adapter = FORECAST_ADAPTERS["live" if live else "replay"]
    st = statuses.get(adapter)
    label = st.label if st else ("NWS gridded forecast" if live else "Archived NBS forecast")
    fc = [i for i in inputs if i.role == "forecast" and i.kind == "series" and i.metric in CORE_FORECAST and i.series]
    if not fc:
        why = f"{st.status}: {st.detail}" if st and st.detail else (st.status if st else "not requested")
        return EvidenceCheck(name="forecast", label=label, status="missing", required=True,
                             detail=f"No usable forecast ({why})."), None
    issued = max((utc(i.source_time) for i in fc if i.source_time), default=None)
    if issued is None or issued > utc(as_of) or _hours(as_of, issued) > FORECAST_MAX_AGE_H:
        when = "unknown" if issued is None else ("after the evaluation time" if issued > utc(as_of)
                                                 else f"{_hours(as_of, issued):.0f} h before the evaluation time")
        return EvidenceCheck(name="forecast", label=label, status="stale", required=True,
                             detail=f"Forecast issue time is {when}; at most {FORECAST_MAX_AGE_H} h is accepted."), None
    retrieved = min(i.fetched_at for i in fc)
    if any(_retrieval_stale(i, as_of, live) for i in fc):
        return EvidenceCheck(name="forecast", label=label, status="stale", required=True,
                             detail=f"Forecast was last retrieved {_fmt(retrieved, tz)}, more than {RETRIEVAL_MAX_AGE_H} h "
                                    "before the evaluation time (an old cached copy)."), None
    hours, t = [], start.replace(minute=0, second=0, microsecond=0)
    while t <= end:
        hours.append(t)
        t += timedelta(hours=1)
    times = sorted({utc(p.t) for i in fc for p in i.series if p.v is not None})
    covered = sum(any(abs(_hours(h, x)) <= 1.5 for x in times) for h in hours)
    coverage = covered / len(hours) if hours else 0.0
    if coverage < COVERAGE_MIN:
        return EvidenceCheck(name="forecast", label=label, status="partial", required=True,
                             detail=f"Forecast covers {coverage:.0%} of the decision window "
                                    f"({_fmt(start, tz)} to {_fmt(end, tz)}); at least {COVERAGE_MIN:.0%} is needed."), coverage
    return EvidenceCheck(name="forecast", label=label, status="ok", required=True,
                         detail=f"Issued {_hours(as_of, issued):.1f} h before the evaluation time; covers {coverage:.0%} "
                                f"of the decision window."), coverage


def _alert_check(inputs, statuses, as_of, live) -> EvidenceCheck:
    adapter = ALERT_ADAPTERS["live" if live else "replay"]
    st = statuses.get(adapter)
    label = st.label if st else "Weather alerts"
    if st is None or st.status in ("unavailable",):
        detail = f"Alert feed unavailable{': ' + st.detail if st and st.detail else ''}. Not knowing about alerts is not the same as none."
        return EvidenceCheck(name="alerts", label=label, status="missing", required=False, detail=detail)
    if st.status == "not_applicable":
        return EvidenceCheck(name="alerts", label=label, status="not_applicable", required=False, detail=st.detail or "")
    alerts = [i for i in inputs if i.role == "alert"]
    if alerts and live and all(_retrieval_stale(i, as_of, live) for i in alerts):
        return EvidenceCheck(name="alerts", label=label, status="stale", required=False,
                             detail=f"Alert feed was last checked more than {RETRIEVAL_MAX_AGE_H} h before the evaluation time.")
    active = [i for i in alerts if i.kind == "alert"]
    if active:
        return EvidenceCheck(name="alerts", label=label, status="ok", required=False, detail=f"{len(active)} alert record(s) checked.")
    return EvidenceCheck(name="alerts", label=label, status="checked_none", required=False,
                         detail="Feed checked: no alerts in effect. On its own this does not show conditions are safe.")


def _obs_check(inputs, statuses, as_of, live) -> EvidenceCheck:
    st = statuses.get("iem_obs")
    label = st.label if st else "Observations"
    ob = [i for i in inputs if i.role == "observation" and i.id.startswith("obs.") and i.source_time
          and utc(i.source_time) <= utc(as_of)]
    if not ob:
        return EvidenceCheck(name="observations", label=label, status="missing", required=False,
                             detail=f"No observations{' (' + st.status + ')' if st else ''}.")
    latest = max(utc(i.source_time) for i in ob)
    if _hours(as_of, latest) > OBS_MAX_AGE_H or any(_retrieval_stale(i, as_of, live) for i in ob):
        return EvidenceCheck(name="observations", label=label, status="stale", required=False,
                             detail=f"Latest observation is {_hours(as_of, latest):.1f} h before the evaluation time "
                                    f"(at most {OBS_MAX_AGE_H} h is accepted), or the cached copy is old.")
    return EvidenceCheck(name="observations", label=label, status="ok", required=False,
                         detail=f"Latest observation {_hours(as_of, latest):.1f} h before the evaluation time.")


def _optional_checks(statuses) -> list[EvidenceCheck]:
    out = []
    for name in sorted(OPTIONAL):
        st = statuses.get(name)
        if st is None:
            continue
        status = {"ok": "ok", "not_applicable": "not_applicable"}.get(st.status, "optional_missing")
        detail = st.detail or ("responded" if st.status == "ok" else st.status)
        if st.status == "empty":
            detail = "No reports returned (optional; seasonal or no data nearby)."
        out.append(EvidenceCheck(name=name, label=st.label, status=status, required=False, detail=detail))
    return out


def _input_fresh(i: NormalizedInput, as_of: datetime, live: bool) -> bool:
    """Usable as positive hazard evidence: retrieved recently (live) and not too old for its role."""
    if _retrieval_stale(i, as_of, live):
        return False
    if i.source_time is None or i.role in ("alert", "context"):
        return True  # alerts in effect count however long ago they were issued
    age = _hours(as_of, i.source_time)
    limit = FORECAST_MAX_AGE_H if i.role == "forecast" else max(OBS_MAX_AGE_H, 6)
    return -1 <= age <= limit


def credible_hazards(hazards: dict[str, HazardResult], rules: list[RuleResult], inputs: list[NormalizedInput],
                     as_of: datetime, live: bool) -> list[str]:
    """Hazards at minor or worse whose controlling rules rest on inputs that are not stale."""
    by_id = {i.id: i for i in inputs}
    rule_by = {r.rule_id: r for r in rules}
    out = []
    for hz in hazards.values():
        if hz.level <= 0:
            continue
        for rid in hz.controlling_rule_ids:
            r = rule_by.get(rid)
            if not r or not r.triggered:
                continue
            ins = [by_id[x] for x in r.input_ids if x in by_id]
            if any(_input_fresh(i, as_of, live) for i in ins) or (not r.input_ids and r.available):
                out.append(f"{hz.label} ({hz.level_name}): {r.label}")
                break
    return out


def assess_sufficiency(inputs: list[NormalizedInput], statuses: list[SourceStatus], hazards: dict[str, HazardResult],
                       rules: list[RuleResult], posture: PostureResult, as_of: datetime, mode: str, timezone: str,
                       timing: dict) -> Sufficiency:
    tz = ZoneInfo(timezone)
    live = _family(mode) == "live"
    by = {s.adapter: s for s in statuses}
    start, end = decision_window(as_of, posture, timing, tz)
    forecast, coverage = _forecast_check(inputs, by, as_of, start, end, live, tz)
    alerts = _alert_check(inputs, by, as_of, live)
    obs = _obs_check(inputs, by, as_of, live)
    optional = _optional_checks(by)
    hazard_evidence = credible_hazards(hazards, rules, inputs, as_of, live)

    core_ok = forecast.status == "ok"
    support_gaps = [c for c in (alerts, obs) if c.status in ("missing", "stale")]
    if core_ok and not support_gaps:
        status: Status = "sufficient"
    elif core_ok or hazard_evidence:
        status = "limited"
    else:
        status = "insufficient"

    reasons = []
    if not core_ok:
        reasons.append(f"Forecast for the decision window: {forecast.detail}")
    for c in support_gaps:
        reasons.append(f"{c.label}: {c.detail}")
    if alerts.status == "checked_none" and not core_ok:
        reasons.append("The alert feed reports nothing in effect, but without a usable forecast that does not show conditions are safe.")
    if hazard_evidence and not core_ok:
        reasons.append("Known hazard evidence is kept: missing data could hide a worse hazard, never a milder one.")

    family = _family(mode)
    when = _fmt(as_of, tz)
    mode_note = {"live": f"Live weather evaluated at {when}.",
                 "replay": f"Replay: evidence judged as of {when}, not current weather.",
                 "backtest": f"Historical reconstruction as of {when}, not current weather.",
                 "livecheck": f"What-if check at another location, evaluated at {when}."}.get(mode, f"Evaluated at {when}.")
    if family == "live" and mode == "live":
        from app.config import settings  # local import keeps the engine importable without app config side effects
        if settings.demo_mode:
            mode_note = f"Demo: cached live weather from {when}, not a fresh download."

    headline = {"sufficient": "Current data is sufficient for this assessment",
                "limited": "Assessment supported, with data limitations",
                "insufficient": "Insufficient current data"}[status]
    return Sufficiency(
        status=status, headline=headline, reasons=reasons,
        missing_sources=[c.label for c in (forecast, alerts, obs) if c.status in ("missing", "partial")],
        stale_sources=[c.label for c in (forecast, alerts, obs) if c.status == "stale"],
        checks=[forecast, alerts, obs, *optional], supports_all_clear=core_ok,
        reason_required=status == "insufficient", hazard_evidence=hazard_evidence,
        window_start=start, window_end=end, forecast_coverage=None if coverage is None else round(coverage, 2),
        evaluated_as_of=utc(as_of), mode=mode, mode_note=mode_note,
    )


NOT_RECORDED = {
    "status": "not_recorded", "headline": "Evidence sufficiency was not recorded for this snapshot",
    "reasons": ["Saved before evidence sufficiency was tracked. It is not assumed to be sufficient."],
    "missing_sources": [], "stale_sources": [], "checks": [], "supports_all_clear": False, "reason_required": True,
    "hazard_evidence": [], "forecast_coverage": None, "policy_version": None,
}


def for_snapshot(snap: dict) -> dict:
    """The recorded sufficiency, or an explicit "not recorded" marker for older snapshots (never sufficient)."""
    return snap.get("sufficiency") or {**NOT_RECORDED, "mode": snap.get("mode"), "evaluated_as_of": snap.get("as_of")}
