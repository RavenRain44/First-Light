"""Recall-first backtest of the current thresholds on the frozen Ames cohort, with corrected labels.

For every cohort day this rebuilds the overnight observations and the day's outcome label from the raw
AMW METARs using only the present-weather group (remarks such as 'LTG DSNT' or 'FZRANO' are ignored),
optionally adds the archived NBM/NBS forecast that was published before 04:00 (IEM, 2019 onward), runs
the decision engine with config/thresholds.yaml, and reports recall first. Thresholds are meant to be
chosen on 2019-2022 and judged on 2023-2026.

Needs the restored dataset (historical_sources/ and cohorts/ beside the database; the app loads it from
Object Storage on startup). Forecast downloads are cached in var/backtest_http_cache.

    python -m scripts.recall_backtest [--forecasts] [--out report.json]
"""
from __future__ import annotations

import argparse
import asyncio
import bisect
import gzip
import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings

PERIODS = (("1996-2018", "1996", "2019"), ("2019-2022 (tune)", "2019", "2023"), ("2023-2026 (held out)", "2023", "2027"))


def metrics(pairs):
    tp = sum(p and o for p, o in pairs)
    fp = sum(p and not o for p, o in pairs)
    fn = sum(o and not p for p, o in pairs)
    tn = len(pairs) - tp - fp - fn
    recall = tp / (tp + fn) if tp + fn else None
    spec = tn / (tn + fp) if tn + fp else None
    return {"n": len(pairs), "disruptive": tp + fn, "caught": tp, "missed": fn, "false_alarms": fp,
            "recall": recall, "precision": tp / (tp + fp) if tp + fp else None,
            "balanced_accuracy": (recall + spec) / 2 if recall is not None and spec is not None else None,
            "accuracy": (tp + tn) / len(pairs) if pairs else None}


async def run(forecasts: bool) -> dict:
    settings.cache_dir = settings.db_path.parent / "backtest_http_cache"  # keep downloads out of fixtures/
    from adapters.historical_asos import present_weather
    from adapters.iem_mos import IEMMOSAdapter
    from app.db import get_engine
    from app.facility import load_facility
    from app.historical import local_instant, observation_inputs, outcome
    from app.risk_experiment import manifest_path
    from engine.evaluate import assess
    from engine.scoring import load_thresholds

    get_engine()
    fac, th = load_facility(), load_thresholds()
    tz = ZoneInfo(fac.timezone)
    manifest = json.loads(manifest_path().read_text())
    src = settings.db_path.parent / "historical_sources"
    years: dict[int, dict] = {}

    def year(y):
        if y not in years:
            p = src / f"AMW-{y}.json.gz"
            data = json.loads(gzip.decompress(p.read_bytes())) if p.exists() else {"rows": [], "url": "", "fetched_at": "1970-01-01T00:00:00+00:00"}
            for r in data["rows"]:
                r["wxcodes"] = present_weather(r["raw"])
            data["times"] = [r["utc_valid"] for r in data["rows"]]
            years[y] = data
        return years[y]

    rows_out = []
    for i, entry in enumerate(manifest["entries"]):
        day = entry["day"]
        d0, as_of = date.fromisoformat(day), local_instant(day, "04:00")
        begin = (datetime.combine(d0, time(), tz) - timedelta(hours=12)).astimezone(timezone.utc).isoformat()
        end = (datetime.combine(d0, time(), tz) + timedelta(hours=37)).astimezone(timezone.utc).isoformat()
        rows = []
        for y in sorted({d0.year - 1, d0.year, d0.year + 1}):
            Y = year(y)
            rows += Y["rows"][bisect.bisect_left(Y["times"], begin):bisect.bisect_right(Y["times"], end)]
        label = outcome(rows, day, fac.timezone)
        if not label["gradable"]:
            continue
        prov = year(d0.year)
        inputs = observation_inputs(rows, as_of, {"url": prov.get("url", ""), "fetched_at": prov["fetched_at"]})
        used_forecast = False
        if forecasts and day >= "2019-01-01":
            fc, status = await IEMMOSAdapter().run(fac, as_of, "backtest")
            inputs += fc
            used_forecast = status.status == "ok"
        posture = assess(inputs, [], fac, as_of, "backtest", th=th, employees=[]).posture.posture
        rows_out.append({"day": day, "disruptive": bool(label["disruptive"]), "posture": posture, "forecast": used_forecast})
        if (i + 1) % 500 == 0:
            print(f"{i + 1}/{len(manifest['entries'])}", flush=True)

    report = {"thresholds_version": th.version, "thresholds_sha256": th.sha256, "forecasts": forecasts,
              "label": "AMW-local-disruption-v1 with present-weather parsing (remarks excluded)", "periods": {}}
    for name, lo, hi in PERIODS:
        part = [r for r in rows_out if lo <= r["day"] < hi]
        report["periods"][name] = metrics([(r["posture"] != "NORMAL", r["disruptive"]) for r in part])
    report["all"] = metrics([(r["posture"] != "NORMAL", r["disruptive"]) for r in rows_out])
    report["missed_days"] = [r["day"] for r in rows_out if r["disruptive"] and r["posture"] == "NORMAL"]
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--forecasts", action="store_true", help="add archived NBS forecasts for 2019 onward (downloads, cached)")
    p.add_argument("--out")
    a = p.parse_args()
    report = asyncio.run(run(a.forecasts))
    if a.out:
        open(a.out, "w", encoding="utf-8").write(json.dumps(report, indent=2))
    for name, m in list(report["periods"].items()) + [("all", report["all"])]:
        if not m["n"]:
            continue
        pct = lambda v: "n/a" if v is None else f"{100 * v:.1f}%"
        print(f"{name:22s} recall {pct(m['recall']):>6} ({m['caught']}/{m['disruptive']})  precision {pct(m['precision']):>6}"
              f"  false alarms {m['false_alarms']:4d}  balanced {pct(m['balanced_accuracy'])}")


if __name__ == "__main__":
    main()
