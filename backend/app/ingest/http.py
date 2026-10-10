from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import httpx

from backend.app.ingest.cache import CacheEntry, ResponseCache


class CachedHTTPClient:
    def __init__(self, user_agent: str, cache: ResponseCache, timeout: float = 15.0) -> None:
        self.user_agent = user_agent
        self.cache = cache
        self.timeout = timeout

    async def get_json(self, url: str, accept: str = "application/geo+json") -> tuple[dict, bool]:
        key = quote_plus(url)
        cached = await self.cache.get(key)
        headers = {"User-Agent": self.user_agent, "Accept": accept}
        if cached and cached.etag:
            headers["If-None-Match"] = cached.etag
        if cached and cached.last_modified:
            headers["If-Modified-Since"] = cached.last_modified
        error: Exception | None = None
        for attempt in range(4):
            try:
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                    response = await client.get(url, headers=headers)
                if response.status_code == 304 and cached:
                    return cached.body, True
                if response.status_code == 429 or response.status_code >= 500:
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        wait = max(1.0, float(retry_after))
                    except ValueError:
                        try:
                            wait = max(
                                1.0,
                                (
                                    parsedate_to_datetime(retry_after) - datetime.now(UTC)
                                ).total_seconds(),
                            )
                        except (TypeError, ValueError):
                            wait = 0.4 * (2**attempt)
                    await asyncio.sleep(min(wait, 4.0))
                    continue
                response.raise_for_status()
                body = response.json()
                entry = CacheEntry(
                    body=body,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                    cached_at=datetime.now(UTC),
                )
                cache_control = response.headers.get("Cache-Control", "")
                max_age = 300
                for part in cache_control.split(","):
                    if "max-age=" in part:
                        try:
                            max_age = int(part.split("=", 1)[1])
                        except ValueError:
                            pass
                await self.cache.set(key, entry, max(30, min(max_age, 3600)))
                return body, False
            except (httpx.HTTPError, ValueError) as exc:
                error = exc
                await asyncio.sleep(0.25 * (2**attempt))
        if cached:
            return cached.body, True
        raise RuntimeError(f"Unable to fetch {url}: {error}") from error
