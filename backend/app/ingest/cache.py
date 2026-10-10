from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol


@dataclass
class CacheEntry:
    body: dict
    etag: str | None
    last_modified: str | None
    cached_at: datetime


class ResponseCache(Protocol):
    async def get(self, key: str) -> CacheEntry | None: ...
    async def set(self, key: str, value: CacheEntry, ttl: int) -> None: ...


class MemoryResponseCache:
    def __init__(self) -> None:
        self.values: dict[str, tuple[CacheEntry, datetime]] = {}

    async def get(self, key: str) -> CacheEntry | None:
        pair = self.values.get(key)
        if not pair or pair[1] < datetime.now(UTC):
            self.values.pop(key, None)
            return None
        return pair[0]

    async def set(self, key: str, value: CacheEntry, ttl: int) -> None:
        self.values[key] = (value, datetime.now(UTC) + timedelta(seconds=ttl))


class ValkeyResponseCache:
    def __init__(self, url: str) -> None:
        from redis.asyncio import from_url

        self.client = from_url(url, decode_responses=True)

    async def get(self, key: str) -> CacheEntry | None:
        raw = await self.client.get(f"firstlight:{key}")
        if not raw:
            return None
        data = json.loads(raw)
        return CacheEntry(
            body=data["body"],
            etag=data.get("etag"),
            last_modified=data.get("last_modified"),
            cached_at=datetime.fromisoformat(data["cached_at"]),
        )

    async def set(self, key: str, value: CacheEntry, ttl: int) -> None:
        await self.client.setex(
            f"firstlight:{key}",
            ttl,
            json.dumps(
                {
                    "body": value.body,
                    "etag": value.etag,
                    "last_modified": value.last_modified,
                    "cached_at": value.cached_at.isoformat(),
                }
            ),
        )
