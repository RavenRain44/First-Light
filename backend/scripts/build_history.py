"""Build the historical event library: verify, replay hourly, attach outcomes, export.

Run from backend/:   python -m scripts.build_history [--only EVENT_ID] [--step 1]

For each candidate event this script
  1. verifies, via the IEM VTEC archive, that the expected NWS products were
     actually issued for the facility's zone/county (unverified events are skipped);
  2. replays the engine hourly from ~24 h before to ~12 h after impact, using only
     data available at each moment (mode "backtest");
  3. attaches outcomes: Local Storm Reports within 25 miles, peak observed gust and
     freezing-precip hours at AMW, worst Iowa DOT corridor condition;
  4. stores everything in SQLite and exports fixtures/history/<event>.json.

All HTTP goes through the on-disk cache, so after one online run the whole
build can be repeated offline with DEMO_MODE=true.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlmodel import delete, select

from adapters import cache
from adapters.base import utc
from adapters.iem_lsr import fetch_lsrs
from adapters.iem_obs import fetch_obhistory, obs_series
from app import snapshots
from app.db import get_engine, session
from app.facility import load_facility
from app.models import HistoryEvent, Snapshot
from engine import analogs

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "history"
BYUGC = "https://mesonet.agron.iastate.edu/json/vtec_events_byugc.php"
CT = ZoneInfo("America/Chicago")


def T(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# Candidates were found by listing every VTEC event for IAZ048 (Story County zone) and
# IAC169 (Story County) in the IEM archive; each is re-verified below before use.
EVENTS = [
    {"id": "derecho-2020-08-10", "name": "Aug 10, 2020 derecho", "hazard": "wind",
     "start": T("2020-08-09T17:00"), "end": T("2020-08-11T04:00"), "impact_day": "2020-08-10",
     "expect": [("IAC169", "SV", "W")],
     "summary": "Fast-moving derecho crossed central Iowa late morning; widespread 70-100+ mph gusts and tree/power damage."},
    {"id": "ice-2023-02-22", "name": "Feb 22, 2023 ice storm", "hazard": "winter",
     "start": T("2023-02-21T11:00"), "end": T("2023-02-23T00:00"), "impact_day": "2023-02-22",
     "expect": [("IAZ048", "IS", "W")],
     "summary": "Freezing rain through the Wednesday morning commute; Ice Storm Warning for Story County."},
    {"id": "blizzard-2022-12-22", "name": "Dec 21-23, 2022 pre-Christmas blizzard", "hazard": "winter",
     "start": T("2022-12-21T12:00"), "end": T("2022-12-23T00:00"), "impact_day": "2022-12-22",
     "expect": [("IAZ048", "WS", "W"), ("IAZ048", "BZ", "W")],
     "summary": "Snow followed by a blizzard and dangerous wind chills over the holiday travel period."},
    {"id": "snow-2024-01-09", "name": "Jan 8-9, 2024 winter storm", "hazard": "winter",
     "start": T("2024-01-08T06:00"), "end": T("2024-01-09T20:00"), "impact_day": "2024-01-09",
     "expect": [("IAZ048", "WS", "W")],
     "summary": "Heavy snow overnight into the Tuesday morning commute."},
    {"id": "wind-2021-12-15", "name": "Dec 15, 2021 high wind / derecho", "hazard": "wind",
     "start": T("2021-12-14T18:00"), "end": T("2021-12-16T06:00"), "impact_day": "2021-12-15",
     "expect": [("IAZ048", "HW", "W"), ("IAC169", "SV", "W")],
     "summary": "Record December warmth with a High Wind Warning and a fast line of severe storms (December derecho)."},
    {"id": "blizzard-2025-03-05", "name": "Mar 4-5, 2025 blizzard and high wind", "hazard": "winter",
     "start": T("2025-03-04T06:00"), "end": T("2025-03-05T20:00"), "impact_day": "2025-03-05",
     "expect": [("IAZ048", "BZ", "W"), ("IAZ048", "HW", "W")],
     "summary": "Rain changing to snow with a Blizzard Warning and a High Wind Warning on Wednesday."},
    {"id": "advisory-2025-02-05", "name": "Feb 5, 2025 winter weather advisory (control case)", "hazard": "winter",
     "start": T("2025-02-04T16:00"), "end": T("2025-02-06T06:00"), "impact_day": "2025-02-05",
     "expect": [("IAZ048", "WW", "Y")],
     "summary": "Advisory-level light wintry mix starting midday Wednesday; included to test for over-calling."},
]


async def verify(ev: dict) -> dict:
    found = []
    d0 = (ev["start"] - timedelta(days=1)).date().isoformat()
    d1 = (ev["end"] + timedelta(days=1)).date().isoformat()
    for ugc, ph, sig in ev["expect"]:
        url = f"{BYUGC}?ugc={ugc}&sdate={d0}&edate={d1}"
        r = await cache.get_json(url, historical=True)
        hits = [e for e in r.data.get("events", []) if e["phenomena"] == ph and e["significance"] == sig]
        found.append({"ugc": ugc, "product": f"{ph}.{sig}", "verified": bool(hits), "source_url": url,
                      "events": [{"name": e["name"], "issue": e["issue"], "expire": e["expire"], "product_id": e["product_id"],
                                  "link": f"https://mesonet.agron.iastate.edu{e['url']}"} for e in hits]})
    return {"ok": all(f["verified"] for f in found), "checks": found}


async def outcomes(ev: dict, timeline: list[dict]) -> dict:
    fac = load_facility()
    lsrs, lsr_url = await fetch_lsrs(fac, ev["start"], ev["end"])
    rows, _ = await fetch_obhistory(fac.asos_station, ev["start"], ev["end"], fac.timezone)
    s = obs_series(rows)
    peak_gust = max(s["wind_gust_mph"], key=lambda x: x[1], default=None)
    fz_hours = sum(1 for _, v in s["freezing_precip"] if v >= 1)
    snow_hours = sum(1 for _, v in s["snow_obs"] if v >= 1)
    worst_road = max((t["road_worst_rank"] for t in timeline if t["road_worst_rank"] is not None), default=None)
    by_type: dict[str, int] = {}
    for x in lsrs:
        by_type[x["typetext"]] = by_type.get(x["typetext"], 0) + 1
    wind_mags = [x["magnitude"] for x in lsrs if x.get("magnitude") and "WND" in (x.get("typetext") or "").upper()]
    snow_mags = [x["magnitude"] for x in lsrs if x.get("magnitude") and "SNOW" in (x.get("typetext") or "").upper()]
    ice_mags = [x["magnitude"] for x in lsrs if x.get("magnitude") and "ICE" in (x.get("typetext") or "").upper()]
    road_names = {0: "normal", 1: "wet/frost", 2: "partially covered", 3: "completely covered", 4: "travel advisory", 5: "not advised/closed"}
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
        parts.append(f"AMW peak gust {peak_gust[1]:.0f} mph")
    if fz_hours:
        parts.append(f"{fz_hours} h of freezing precip at AMW")
    if worst_road is not None:
        parts.append(f"worst commute corridor: {road_names[int(worst_road)]}")
    severe = bool((wind_mags and max(wind_mags) >= 58) or (peak_gust and peak_gust[1] >= 58) or (worst_road or 0) >= 3
                  or fz_hours >= 2 or (snow_mags and max(snow_mags) >= 6) or (ice_mags and max(ice_mags) >= 0.1))
    return {
        "summary": "; ".join(parts) + ".",
        "severe_impact": severe,
        "lsr_count": len(lsrs), "lsr_by_type": by_type, "lsr_source_url": lsr_url,
        "lsrs": lsrs[:40],
        "max_reported_wind_mph": max(wind_mags) if wind_mags else None,
        "max_reported_snow_in": max(snow_mags) if snow_mags else None,
        "max_reported_ice_in": max(ice_mags) if ice_mags else None,
        "amw_peak_gust_mph": round(peak_gust[1], 1) if peak_gust else None,
        "amw_peak_gust_time": peak_gust[0].isoformat() if peak_gust else None,
        "amw_freezing_precip_hours": fz_hours, "amw_snow_hours": snow_hours,
        "worst_corridor_rank": worst_road,
        "amw_obs_note": "AMW ASOS stopped reporting during the derecho (power loss); LSRs are the ground truth." if ev["id"].startswith("derecho") else None,
    }


def backtest_summary(ev: dict, timeline: list[dict], outcome: dict) -> dict:
    """Recommended posture at 04:00 local on the impact day vs. what happened."""
    y, m, d = map(int, ev["impact_day"].split("-"))
    four = datetime(y, m, d, 4, tzinfo=CT).astimezone(timezone.utc)
    at4 = min(timeline, key=lambda t: abs(datetime.fromisoformat(t["as_of"]) - four))
    first_non_normal = next((t for t in timeline if t["posture"] != "NORMAL"), None)
    order = ["NORMAL", "DELAYED_ARRIVAL", "EARLY_DISMISSAL", "TELEWORK", "CLOSED"]
    peak = max(timeline, key=lambda t: order.index(t["posture"]))
    rec = at4["posture"]
    if outcome["severe_impact"] and rec == "NORMAL":
        verdict = "missed at 04:00" + (f"; first non-normal at {datetime.fromisoformat(first_non_normal['as_of']).astimezone(CT):%a %H:%M %Z}"
                                       if first_non_normal else "; never flagged")
    elif outcome["severe_impact"]:
        verdict = "consistent: action recommended before impact"
    elif rec != "NORMAL":
        verdict = "possible over-call: action recommended, limited observed impact"
    else:
        verdict = "consistent: no action, limited impact"
    return {
        "at_0400_local": {"as_of": at4["as_of"], "posture": rec, "confidence": at4["confidence"],
                          "decision_day": at4["decision_day"], "readiness": at4.get("readiness")},
        "first_orange_or_red": next(({"as_of": t["as_of"], "readiness": t["readiness"]} for t in timeline
                                     if t.get("readiness") in ("ORANGE", "RED")), None),
        "first_non_normal": first_non_normal and {"as_of": first_non_normal["as_of"], "posture": first_non_normal["posture"]},
        "peak_posture": {"as_of": peak["as_of"], "posture": peak["posture"]},
        "outcome_severe": outcome["severe_impact"],
        "verdict": verdict,
        "label": "simulated by rules (backtest)",
    }


async def build_event(ev: dict, step: int) -> None:
    fac = load_facility()
    v = await verify(ev)
    if not v["ok"]:
        print(f"!! {ev['id']}: expected products not found in the archive; skipping", json.dumps(v["checks"])[:300])
        return
    with session() as s:
        s.exec(delete(Snapshot).where(Snapshot.event_id == ev["id"], Snapshot.mode == "backtest"))
        s.exec(delete(HistoryEvent).where(HistoryEvent.id == ev["id"]))
        s.commit()
    timeline = []
    t = ev["start"]
    while t <= ev["end"]:
        snap = await snapshots.evaluate(fac, t, "backtest", event_id=ev["id"], use_ai=False)
        sig = snap["signals"]
        timeline.append({
            "snapshot_id": snap["snapshot_id"], "as_of": snap["as_of"], "posture": snap["posture"]["posture"],
            "decision_day": snap["posture"]["decision_day"], "confidence": snap["confidence"]["level"],
            "readiness": snap["readiness"]["level"] if snap.get("readiness") else None,
            "scores": {k: h["score"] for k, h in snap["hazards"].items()},
            "alerts": sorted({a["event"] for a in snap.get("alerts", [])}),
            "road_worst_rank": sig["road_worst_rank"]["value"] if sig["road_worst_rank"]["available"] else None,
            "features": snap["features"],
        })
        print(f"   {ev['id']} {t:%Y-%m-%d %H:%MZ} -> {timeline[-1]['posture']:<16} {timeline[-1]['readiness'] or '':<7} {timeline[-1]['confidence']:<6} {timeline[-1]['alerts']}")
        t += timedelta(hours=step)
    out = await outcomes(ev, timeline)
    bt = backtest_summary(ev, timeline, out)
    with session() as s:
        s.add(HistoryEvent(id=ev["id"], name=ev["name"], hazard=ev["hazard"], start=ev["start"], end=ev["end"],
                           impact_day=ev["impact_day"], summary=ev["summary"], verification_json=json.dumps(v),
                           outcome_json=json.dumps(out, default=str), backtest_json=json.dumps(bt)))
        s.commit()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{ev['id']}.json").write_text(json.dumps({
        "event": {k: (v_.isoformat() if isinstance(v_, datetime) else v_) for k, v_ in ev.items() if k != "expect"},
        "verification": v, "outcome": out, "backtest": bt, "timeline": timeline,
        "note": "Postures are simulated by the rules engine (backtest), not real USDA decisions.",
    }, indent=1, default=str), encoding="utf-8")
    print(f"== {ev['id']}: 04:00 -> {bt['at_0400_local']['posture']}; outcome severe={out['severe_impact']}; {bt['verdict']}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--step", type=int, default=1)
    args = ap.parse_args()
    get_engine()
    for ev in EVENTS:
        if args.only and ev["id"] != args.only:
            continue
        print(f"-- {ev['name']}")
        await build_event(ev, args.step)
    analogs.reset()
    await cache.aclose()


if __name__ == "__main__":
    asyncio.run(main())
