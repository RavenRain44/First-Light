"""Backtest the AI explanation writer on stored historical days.

The AI never decides: the operating status comes from the deterministic rules. What can go wrong is
the writing, so this checks, on a sample of past days, how often the model's brief passes the same
validation the live app applies (names the computed status, recommends nothing else, every number
comes from the snapshot, cites only triggered rules, says the manager decides), how often it needed
its repair attempt, and how often the app had to fall back to the deterministic template.

Each sampled day costs real model calls (up to 2 Akamai + 1 Strands). Without --yes this only prints
the sample. Nothing is written to the database; a JSON report goes to var/ai_backtest/.

Run from backend/:  python -m scripts.backtest_ai --limit 100 --yes
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import time
from collections import Counter
from datetime import datetime, timezone

from sqlmodel import select

from ai.agent import interpret, model_enabled
from app import historical
from app.config import settings
from app.db import session
from app.models import HistoricalEvaluation

PROBLEM_KINDS = [  # validation message -> short category
    (r"does not name the recommended posture", "did not name the computed status"),
    (r"brief recommends", "recommended a different status"),
    (r"numbers not found", "number not in the data"),
    (r"rule that did not trigger|cite up to three", "cited a rule that did not trigger"),
    (r"suggested reasons", "reason text broke the evidence-only rule"),
    (r"unknown alert", "summarised an alert that does not exist"),
    (r"manager makes the final decision", "did not say the manager decides"),
    (r"not configured|model call failed", "call failed (network/auth/timeout)"),
    (r"invalid structured response|did not finish|no content", "malformed answer"),
]


def kind(problem: str) -> str:
    return next((k for pat, k in PROBLEM_KINDS if re.search(pat, problem, re.I)), "other")


def sample(limit: int, mode: str, seed: int) -> list[dict]:
    """Up to half the sample from days the rules flagged (where the writing matters most), the rest quiet days."""
    with session() as s:
        rows = [json.loads(r.summary_json) for r in s.exec(select(HistoricalEvaluation)).all()]
    rows = [r for r in rows if r["requested_mode"] == mode and r.get("recommendation")]
    latest: dict[str, dict] = {}
    for r in rows:  # one attempt per day
        latest[r["day"]] = r
    flagged = [r for r in latest.values() if r["recommendation"] != "NORMAL"]
    quiet = [r for r in latest.values() if r["recommendation"] == "NORMAL"]
    rng = random.Random(seed)
    take = rng.sample(flagged, min(len(flagged), limit // 2))
    take += rng.sample(quiet, min(len(quiet), limit - len(take)))
    return sorted(take, key=lambda r: r["day"])


async def run(days: list[dict]) -> dict:
    results = []
    for i, row in enumerate(days, 1):
        snap = historical.lookup(row["id"])
        if not snap:
            continue
        snap["analogs"] = snap.get("analogs") or snap.get("analogs_addon")
        t0 = time.monotonic()
        brief, model_id = await interpret(snap, use_model=True)
        inf, val = brief.get("inference", {}), brief.get("validation", {})
        tokens = sum(((r or {}).get("usage") or {}).get("total_tokens", 0) for r in inf.get("requests", []))
        status = ("accepted_first_try" if val.get("ok") and val.get("attempts") == 1 else
                  "accepted_after_repair" if val.get("ok") else "template_fallback")
        problems = [p for f in inf.get("failures", []) for p in f.get("problems", [])]
        results.append({"day": row["day"], "status_computed": snap["posture"]["posture"], "result": status,
                        "provider": inf.get("provider"), "model_id": model_id, "attempts": val.get("attempts"),
                        "problems": problems, "tokens": tokens, "seconds": round(time.monotonic() - t0, 2),
                        "headline": brief.get("headline")})
        print(f"[{i}/{len(days)}] {row['day']} {snap['posture']['posture']}: {status}"
              + (f" ({'; '.join(problems)[:140]})" if problems else ""), flush=True)
    return summarise(results)


def summarise(results: list[dict]) -> dict:
    n = len(results)
    by_result = Counter(r["result"] for r in results)
    by_status = {}
    for s in sorted({r["status_computed"] for r in results}):
        sub = [r for r in results if r["status_computed"] == s]
        by_status[s] = {"n": len(sub), **Counter(r["result"] for r in sub)}
    attempts_with_problems = Counter(kind(p) for r in results for p in r["problems"])
    return {
        "what_this_measures": "Whether the AI's written brief passed the app's own validation. The operating status is "
                              "computed by the rules and is not changed by the AI, so this is not a weather-accuracy score.",
        "n_days": n, "results": dict(by_result),
        "accepted_rate": (by_result["accepted_first_try"] + by_result["accepted_after_repair"]) / n if n else None,
        "first_try_rate": by_result["accepted_first_try"] / n if n else None,
        "by_computed_status": by_status,
        "rejected_attempts_by_problem": dict(attempts_with_problems.most_common()),
        "providers": dict(Counter(r["provider"] for r in results)),
        "total_tokens": sum(r["tokens"] for r in results),
        "median_seconds": sorted(r["seconds"] for r in results)[n // 2] if n else None,
        "status": "not enough data" if n < 30 else "descriptive estimate",
        "days": results,
    }


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--mode", choices=["archive", "observation"], default="archive")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--yes", action="store_true", help="make the paid model calls")
    a = p.parse_args()
    days = sample(a.limit, a.mode, a.seed)
    flagged = sum(d["recommendation"] != "NORMAL" for d in days)
    print(f"Sample: {len(days)} {a.mode} days ({flagged} flagged by the rules, {len(days) - flagged} normal), "
          f"up to {len(days) * 3} model calls.")
    if not a.yes:
        print("Dry run. Add --yes to make the calls.")
        return
    if settings.model_provider == "none" or not model_enabled():
        raise SystemExit("AI is off (MODEL_PROVIDER=none or no AKAMAI_API_KEY / Strands). Configure it in .env first.")
    report = await run(days)
    report.update({"mode": a.mode, "seed": a.seed, "created_at": datetime.now(timezone.utc).isoformat()})
    out = settings.db_path.parent / "ai_backtest"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"ai_backtest_{a.mode}_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != "days"}, indent=1, default=str))
    print("Report:", path)


if __name__ == "__main__":
    asyncio.run(main())
