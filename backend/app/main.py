"""Closure Call API. Run from backend/:  uvicorn app.main:app --reload --port 8000"""
from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from adapters import cache
from app import snapshots
from app.config import REPO_DIR, settings
from app.db import get_engine
from app.facility import load_facility
from app.routers import core, history, livecheck

log = logging.getLogger("closurecall")


async def _refresh_loop():
    """Optional periodic live refresh (REFRESH_INTERVAL_SECONDS > 0)."""
    while True:
        await asyncio.sleep(settings.refresh_interval_seconds)
        try:
            await snapshots.evaluate(load_facility(), None, "live")
        except Exception:  # noqa: BLE001
            log.exception("scheduled refresh failed")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    get_engine()
    task = asyncio.create_task(_refresh_loop()) if settings.refresh_interval_seconds > 0 and not settings.demo_mode else None
    yield
    if task:
        task.cancel()
    await cache.aclose()


app = FastAPI(title="Closure Call", version="0.1.0", lifespan=lifespan,
              description="Weather-driven facility operating-status decision support (USDA AI Challenge, Hack Midwest 2026)")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(core.router)
app.include_router(history.router)
app.include_router(livecheck.router)

# Production container serves the built dashboard and API from one origin.
# Vite remains the normal development server when no build is present.
web_dist = REPO_DIR / "frontend" / "dist"
if web_dist.is_dir():
    app.mount("/", StaticFiles(directory=web_dist, html=True), name="dashboard")
