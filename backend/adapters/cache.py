"""On-disk HTTP cache keyed by URL (+ an optional trim name).

IEM asks clients not to hammer the service, and the demo must survive flaky
Wi-Fi, so every upstream GET goes through here:

* live requests are reused for `live_ttl_seconds` (default 10 min);
* historical requests (anything with a past `valid=`/`runtime=`/`date=`) are
  cached forever;
* with DEMO_MODE=true nothing is fetched; a cache miss is reported as the
  source being unavailable. The Live Check path passes `allow_demo_bypass`.

Entries are JSON files in fixtures/http_cache so a built cache can be committed.
`trim` lets an adapter shrink a large statewide/national payload before it is
stored (e.g. keep only road segments near the facility).
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from app.config import settings


class SourceUnavailable(Exception):
    """Raised when a source cannot be fetched (network error, HTTP error, demo cache miss)."""


@dataclass
class CachedResponse:
    url: str
    fetched_at: datetime
    data: Any
    from_cache: bool


_locks: dict[str, asyncio.Lock] = {}
_client: httpx.AsyncClient | None = None
_iem_gate = asyncio.Semaphore(2)  # at most two concurrent IEM requests


def _client_get() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            headers={"User-Agent": settings.nws_user_agent, "Accept": "application/geo+json, application/json"},
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )
    return _client


def cache_key(url: str, trim: str | None) -> str:
    return hashlib.sha1(f"{url}|{trim or ''}".encode()).hexdigest()


def _path(key: str):
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    return settings.cache_dir / f"{key}.json.gz"


def _read(path) -> dict | None:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError, EOFError):
        return None


def _write(path, obj: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as fh:
        json.dump(obj, fh, separators=(",", ":"))
    tmp.replace(path)


async def get_json(
    url: str,
    *,
    historical: bool = False,
    trim: tuple[str, Callable[[Any], Any]] | None = None,
    allow_demo_bypass: bool = False,
    ttl: int | None = None,
) -> CachedResponse:
    trim_name = trim[0] if trim else None
    key = cache_key(url, trim_name)
    path = _path(key)
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _read(path) if path.exists() else None
        demo = settings.demo_mode and not allow_demo_bypass
        if cached is not None and "error" in cached and (historical or demo):
            raise SourceUnavailable(cached["error"])
        if cached is not None and "error" in cached:
            cached = None
        if cached is not None:
            age = time.time() - cached["fetched_at_epoch"]
            if demo or historical or age < (ttl if ttl is not None else settings.live_ttl_seconds):
                return CachedResponse(
                    url, datetime.fromtimestamp(cached["fetched_at_epoch"], timezone.utc), cached["data"], True
                )
        if demo:
            raise SourceUnavailable(f"DEMO_MODE: no cached response for {url}")
        try:
            gate = _iem_gate if "mesonet.agron.iastate.edu" in url else None
            if gate:
                async with gate:
                    resp = await _client_get().get(url)
            else:
                resp = await _client_get().get(url)
        except httpx.HTTPError as e:
            if cached is not None:  # stale beats nothing; caller sees the real fetched_at
                return CachedResponse(
                    url, datetime.fromtimestamp(cached["fetched_at_epoch"], timezone.utc), cached["data"], True
                )
            raise SourceUnavailable(f"{type(e).__name__}: {e}") from e
        if resp.status_code >= 400:
            if cached is not None:
                return CachedResponse(
                    url, datetime.fromtimestamp(cached["fetched_at_epoch"], timezone.utc), cached["data"], True
                )
            msg = f"HTTP {resp.status_code} from {url}: {resp.text[:200]}"
            if historical and 400 <= resp.status_code < 500 and resp.status_code != 429:
                # Archives don't change: remember "no data for this run/time" instead of re-asking.
                _write(path, {"url": url, "trim": trim_name, "fetched_at_epoch": time.time(), "error": msg})
            raise SourceUnavailable(msg)
        try:
            data = resp.json()
        except ValueError as e:
            raise SourceUnavailable(f"non-JSON response from {url}") from e
        if trim:
            data = trim[1](data)
        now = time.time()
        _write(path, {"url": url, "trim": trim_name, "fetched_at_epoch": now, "data": data})
        return CachedResponse(url, datetime.fromtimestamp(now, timezone.utc), data, False)


async def aclose() -> None:
    if _client is not None:
        await _client.aclose()


def cached_fetched_at(url: str, trim: str | None = None) -> datetime | None:
    """When the cached copy of ``url`` was fetched (None if not cached)."""
    path = _path(cache_key(url, trim))
    d = _read(path) if path.exists() else None
    return datetime.fromtimestamp(d["fetched_at_epoch"], timezone.utc) if d and "data" in d else None
