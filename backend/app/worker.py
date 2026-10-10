from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.app.api.main import _build_runtime
from backend.app.config import get_settings
from backend.app.engine import evaluate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("firstlight.worker")


async def main() -> None:
    state = _build_runtime(get_settings())

    async def poll() -> None:
        for facility in state.repository.list_facilities():
            if facility.is_teleported:
                continue
            try:
                evidence = await state.ingest.collect(facility)
                recommendation = evaluate(facility, evidence, evidence.as_of, state.registry)
                state.repository.save_recommendation(recommendation, evidence)
                logger.info("Refreshed %s: %s", facility.id, recommendation.posture.value)
            except Exception:
                logger.exception("Refresh failed visibly for %s", facility.id)

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        poll, "interval", seconds=state.settings.poll_interval_seconds, max_instances=1
    )
    scheduler.start()
    await poll()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
