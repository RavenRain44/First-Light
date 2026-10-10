"""Pre-cache Iowa DOT camera images so the offline demo (DEMO_MODE=true) can show them.

Run from backend/ (online):  python -m scripts.cache_cameras [--replay-step 3] [--no-replay]

  * Live: every view of the 20 cameras nearest the facility, refreshing the cached
    camera list at the same time so list and images match.
  * Replay: for each historical event, the impact day (00:00-18:00 local) on a
    3-hour grid, main view only, for the 20 nearest cameras.

Images go to backend/var/camera_cache (git-ignored; roughly 50-70 MB). In demo mode
any camera without a cached image is simply not shown.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlmodel import select

from adapters import cache
from adapters.iem_cameras import fetch_cameras, get_image, is_cached, save_demo_list
from adapters.iem_roads import archive_time
from app.config import settings
from app.db import session
from app.facility import load_facility
from app.models import HistoryEvent

CONCURRENCY = 4  # gentle on IEM's archive


async def _grab(urls: list[str]) -> tuple[int, int]:
    gate = asyncio.Semaphore(CONCURRENCY)
    got = skipped = 0

    async def one(u: str):
        nonlocal got, skipped
        if is_cached(u):
            skipped += 1
            return
        async with gate:
            if await get_image(u) is not None:
                got += 1

    await asyncio.gather(*(one(u) for u in urls))
    return got, skipped


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay-step", type=int, default=3)
    ap.add_argument("--no-replay", action="store_true")
    args = ap.parse_args()
    if settings.demo_mode:
        raise SystemExit("Run this online (DEMO_MODE=false): it downloads images for later offline use.")
    f = load_facility()

    # Live: force a fresh camera list so the cached list and images are from the same moment.
    settings.live_ttl_seconds = 0
    now = datetime.now(timezone.utc)
    cams, _ = await fetch_cameras(f, now, live=True)
    urls = [v["url"] for c in cams for v in c["views"]]
    got, skipped = await _grab(urls)
    # Pin exactly this list for DEMO_MODE so later online browsing can't swap in uncached frames.
    save_demo_list([{**c, "views": [v for v in c["views"] if is_cached(v["url"])]} for c in cams], now)
    print(f"live: {len(cams)} cameras, {len(urls)} views -> {got} downloaded, {skipped} already cached")

    if args.no_replay:
        return
    with session() as s:
        events = s.exec(select(HistoryEvent).order_by(HistoryEvent.start)).all()
    if not events:
        print("no historical events in the database; run scripts.build_history first for replay images")
    tz = ZoneInfo(f.timezone)
    for e in events:
        y, m, d = map(int, e.impact_day.split("-"))
        t = archive_time(datetime(y, m, d, 0, tzinfo=tz))
        end = datetime(y, m, d, 18, tzinfo=tz).astimezone(timezone.utc)
        urls = []
        while t <= end:
            try:
                cams, _ = await fetch_cameras(f, t + timedelta(minutes=59), live=False)
            except cache.SourceUnavailable:
                cams = []
            urls += [c["views"][0]["url"] for c in cams if c["views"]]
            t += timedelta(hours=args.replay_step)
        got, skipped = await _grab(sorted(set(urls)))
        print(f"{e.id}: {len(set(urls))} images -> {got} downloaded, {skipped} already cached")
    await cache.aclose()


if __name__ == "__main__":
    asyncio.run(main())
