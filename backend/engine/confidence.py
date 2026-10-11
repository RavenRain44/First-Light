"""Confidence = data completeness x freshness x agreement x alert certainty.

Each factor is 0..1 with a plain-language explanation; the weighted total maps
to high (>= 0.75), medium (>= 0.5) or low.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel

from adapters.base import NormalizedInput, SourceStatus, utc
from engine.features import Context
from engine.scoring import HazardResult, RuleResult

# Expected sources and their weight toward completeness, by mode.
EXPECTED = {
    "live": {"nws_alerts": 0.30, "nws_grid": 0.30, "iem_obs": 0.20, "iem_roads": 0.10, "iem_rwis": 0.05, "iem_outlook": 0.05},
    "replay": {"iem_vtec": 0.30, "iem_mos": 0.30, "iem_obs": 0.20, "iem_roads": 0.10, "iem_rwis": 0.05, "iem_outlook": 0.05},
}
WEIGHTS = {"completeness": 0.35, "freshness": 0.25, "agreement": 0.25, "certainty": 0.15}
CERTAINTY = {"Observed": 1.0, "Likely": 0.9, "Possible": 0.6, "Unlikely": 0.4, "Unknown": 0.5}


class Factor(BaseModel):
    name: str
    score: float
    weight: float
    explanation: str


class Confidence(BaseModel):
    level: str
    score: float
    factors: list[Factor]


def _completeness(statuses: list[SourceStatus], mode: str, as_of: datetime) -> Factor:
    exp = dict(EXPECTED["live" if mode in ("live", "livecheck") else "replay"])
    if utc(as_of).month in (5, 6, 7, 8, 9):
        exp.pop("iem_roads", None)  # Iowa DOT winter reporting is seasonal; not expected in summer
    by = {s.adapter: s for s in statuses}
    got, missing = 0.0, []
    for name, w in exp.items():
        s = by.get(name)
        if s and s.status in ("ok", "empty"):
            got += w
        else:
            missing.append(f"{s.label if s else name} ({s.status if s else 'not run'})")
    total = sum(exp.values())
    sc = got / total if total else 0.0
    expl = "All expected sources responded." if not missing else "Missing: " + "; ".join(missing)
    return Factor(name="completeness", score=round(sc, 2), weight=WEIGHTS["completeness"], explanation=expl)


def _freshness(inputs: list[NormalizedInput], as_of: datetime) -> Factor:
    as_of = utc(as_of)
    notes, parts = [], []
    fc = [i for i in inputs if i.role == "forecast" and i.kind == "series" and i.source_time]
    if fc:
        age = (as_of - utc(max(i.source_time for i in fc))).total_seconds() / 3600
        s = 1.0 if age <= 6 else 0.6 if age <= 12 else 0.3
        parts.append(s)
        notes.append(f"forecast issued {age:.1f} h before as-of")
    elif any(i.role == "forecast" and (i.data or {}).get("live_retrieval_only") for i in inputs):
        parts.append(0.5)
        notes.append("live backup forecast retrieved; exact model issue time unavailable")
    else:
        parts.append(0.0)
        notes.append("no forecast")
    ob = [i for i in inputs if i.role == "observation" and i.kind == "series" and i.source_time]
    if ob:
        age = (as_of - utc(max(i.source_time for i in ob))).total_seconds() / 3600
        s = 1.0 if age <= 1.5 else 0.6 if age <= 3 else 0.2
        parts.append(s)
        notes.append(f"latest observation {age:.1f} h old" + (" (station may be down)" if age > 1.5 else ""))
    else:
        parts.append(0.0)
        notes.append("no observations")
    sc = sum(parts) / len(parts)
    return Factor(name="freshness", score=round(sc, 2), weight=WEIGHTS["freshness"], explanation="; ".join(notes))


def _agreement(ctx: Context, inputs: list[NormalizedInput], hazards: dict[str, HazardResult]) -> Factor:
    by = {i.id: i for i in inputs}
    checks, notes = [], []
    h = ctx.as_of.replace(minute=0, second=0, microsecond=0)

    def at(key, t):
        inp = by.get(key)
        if not inp or not inp.series:
            return None
        vals = [p.v for p in inp.series if p.v is not None and abs((utc(p.t) - t).total_seconds()) <= 3600]
        return vals[0] if vals else None

    for metric, tol, unit in (("wind_gust_mph", 10, "mph"), ("temp_f", 5, "F")):
        f = at(f"fcst.{metric}", h)
        # A forecast gust is an expected peak, so compare it with the observed peak gust when available.
        okey = "obs.peak_gust_mph" if metric == "wind_gust_mph" and "obs.peak_gust_mph" in by else f"obs.{metric}"
        o = at(okey, h) or at(okey, h - timedelta(hours=1))
        if f is None or o is None:
            continue
        d = abs(f - o)
        checks.append(1.0 if d <= tol else 0.5 if d <= 2 * tol else 0.0)
        notes.append(f"{metric.split('_')[0] if metric != 'wind_gust_mph' else 'gust'} forecast {f:.0f} vs observed {o:.0f} {unit}")

    alerts = {a.get("event", "") for a in ctx.alerts}
    sig = ctx.signals
    winter_alert = any(k in e for e in alerts for k in ("Winter", "Ice Storm", "Blizzard"))
    if winter_alert and sig["fcst_ice_24h_in"].available and sig["fcst_snow_24h_in"].available:
        precip = (sig["fcst_ice_24h_in"].value or 0) + (sig["fcst_snow_24h_in"].value or 0)
        checks.append(1.0 if precip >= 0.05 else 0.3)
        notes.append(f"winter alert vs forecast ice+snow {precip:.2f} in" + (" (disagree)" if precip < 0.05 else ""))
    wind_alert = any(k in e for e in alerts for k in ("High Wind", "Severe Thunderstorm Warning", "Tornado Warning"))
    if wind_alert and sig["fcst_max_gust_24h_mph"].available:
        g = sig["fcst_max_gust_24h_mph"].value or 0
        checks.append(1.0 if g >= 45 else 0.4)
        notes.append(f"wind warning vs forecast max gust {g:.0f} mph" + (" (forecast much weaker than warning)" if g < 45 else ""))
    for hz in hazards.values():
        if hz.level >= 2 and not any(a for a in ctx.alerts):
            checks.append(0.6)
            notes.append(f"{hz.label} at {hz.level_name} from data alone, no NWS alert in effect")
    if not checks:
        return Factor(name="agreement", score=0.7, weight=WEIGHTS["agreement"],
                      explanation="No overlapping forecast/observation pairs to compare (neutral).")
    return Factor(name="agreement", score=round(sum(checks) / len(checks), 2), weight=WEIGHTS["agreement"],
                  explanation="; ".join(notes))


def _certainty(ctx: Context, rules: list[RuleResult], hazards: dict[str, HazardResult]) -> Factor:
    active = [hz for hz in hazards.values() if hz.level > 0]
    if not active:
        return Factor(name="certainty", score=0.85, weight=WEIGHTS["certainty"],
                      explanation="No hazard thresholds crossed; nothing contingent on an uncertain alert.")
    ctrl = {rid for hz in active for rid in hz.controlling_rule_ids}
    alert_rules = [r for r in rules if r.rule_id in ctrl and r.metric == "alert_present"]
    if not alert_rules:
        return Factor(name="certainty", score=0.6, weight=WEIGHTS["certainty"],
                      explanation="Recommendation rests on forecast/observed thresholds, not an NWS alert.")
    events = {e.strip() for r in alert_rules for e in str(r.observed_value).split(",")}
    certs = [a.get("certainty") or "Unknown" for a in ctx.alerts if a.get("event") in events]
    sc = max(CERTAINTY.get(c, 0.5) for c in certs) if certs else 0.5
    inferred = any("inferred_fields" in a for a in ctx.alerts if a.get("event") in events)
    return Factor(name="certainty", score=sc, weight=WEIGHTS["certainty"],
                  explanation=f"Controlling alert certainty: {', '.join(sorted(set(certs)))}" +
                              (" (inferred from VTEC significance)" if inferred else ""))


def compute(statuses, inputs, ctx, rules, hazards, mode) -> Confidence:
    factors = [
        _completeness(statuses, mode, ctx.as_of),
        _freshness(inputs, ctx.as_of),
        _agreement(ctx, inputs, hazards),
        _certainty(ctx, rules, hazards),
    ]
    total = sum(f.score * f.weight for f in factors) / sum(f.weight for f in factors)
    if any(i.role == "forecast" and (i.data or {}).get("weather_fallback") for i in inputs):
        total = min(total, 0.65)
        factors.append(Factor(name="secondary_forecast", score=0.65, weight=0,
                              explanation="Backup model in use: confidence is capped at medium; source limitations remain explicit. This score is not a calibrated accuracy probability."))
    level = "high" if total >= 0.75 else "medium" if total >= 0.5 else "low"
    return Confidence(level=level, score=round(total, 2), factors=factors)
