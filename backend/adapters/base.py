"""Adapter interface and the normalized input record every source produces.

Every adapter implements ``fetch(facility, as_of) -> list[NormalizedInput]`` and
declares ``supports_historical`` and ``coverage``. Iowa-only sources declare
``coverage = "IA"`` so a future multi-state source registry can choose adapters
per facility; that registry is intentionally not built.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from adapters.cache import SourceUnavailable


class Corridor(BaseModel):
    id: str
    name: str
    coordinates: list[list[float]]  # [[lon, lat], ...]


class Facility(BaseModel):
    id: str
    name: str
    synthetic: bool = True
    lat: float
    lon: float
    state: str
    timezone: str = "America/Chicago"
    asos_station: str | None = None  # IEM id, e.g. AMW
    mos_station: str | None = None  # ICAO, e.g. KAMW
    nws_office: str | None = None
    hours: dict[str, str] = Field(default_factory=lambda: {"open": "07:30", "close": "16:30"})
    commute_windows: dict[str, list[str]] = Field(
        default_factory=lambda: {"am": ["06:00", "08:00"], "pm": ["16:00", "18:00"]}
    )
    building_type: str | None = None
    accessibility_notes: list[str] = Field(default_factory=list)
    corridors: list[Corridor] = Field(default_factory=list)
    hypothetical: bool = False  # True for Live Check what-if copies


class Point(BaseModel):
    t: datetime
    v: float | None


class NormalizedInput(BaseModel):
    """One normalized input with its provenance. Stored verbatim in snapshots."""

    id: str  # stable id rules refer to, e.g. "fcst.wind_gust_mph"
    kind: Literal["series", "scalar", "alert", "road", "outlook", "report"]
    role: Literal["forecast", "observation", "alert", "context"]
    metric: str
    unit: str | None = None
    value: float | str | None = None
    series: list[Point] | None = None
    data: dict[str, Any] | None = None
    source: str  # human name of the source
    source_url: str
    fetched_at: datetime
    source_time: datetime | None = None  # timestamp the source itself reports (issue/update/obs time)
    note: str | None = None


class SourceStatus(BaseModel):
    adapter: str
    label: str
    status: Literal["ok", "unavailable", "not_applicable", "empty"]
    detail: str | None = None
    fetched_at: datetime | None = None
    source_time: datetime | None = None
    urls: list[str] = Field(default_factory=list)
    n_inputs: int = 0
    elapsed_ms: int = 0


class Adapter(ABC):
    name: str = "base"
    label: str = "Base"
    supports_historical: bool = False
    coverage: str = "US"  # "US" or a two-letter state
    roles: tuple[str, ...] = ()

    def covers(self, facility: Facility) -> bool:
        return self.coverage == "US" or facility.state == self.coverage

    def applicable(self, facility: Facility, as_of: datetime, mode: str) -> str | None:
        """Return a reason string if this adapter must not run for this request."""
        if not self.covers(facility):
            return f"source covers {self.coverage} only"
        if mode != "live" and not self.supports_historical:
            return "source has no archive; not used in replay"
        if mode == "live" and self.historical_only:
            return "replay-only source"
        return None

    historical_only: bool = False

    @abstractmethod
    async def fetch(self, facility: Facility, as_of: datetime) -> list[NormalizedInput]: ...

    async def run(self, facility: Facility, as_of: datetime, mode: str) -> tuple[list[NormalizedInput], SourceStatus]:
        reason = self.applicable(facility, as_of, mode)
        if reason:
            return [], SourceStatus(adapter=self.name, label=self.label, status="not_applicable", detail=reason)
        self._urls: list[str] = []
        t0 = time.perf_counter()
        try:
            inputs = await self.fetch(facility, as_of)
        except SourceUnavailable as e:
            return [], SourceStatus(
                adapter=self.name, label=self.label, status="unavailable", detail=str(e)[:300],
                urls=self._urls, elapsed_ms=int((time.perf_counter() - t0) * 1000),
            )
        except Exception as e:  # noqa: BLE001 - one bad source must never break an evaluation
            return [], SourceStatus(
                adapter=self.name, label=self.label, status="unavailable",
                detail=f"{type(e).__name__}: {e}"[:300], urls=self._urls,
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            )
        fetched = max((i.fetched_at for i in inputs), default=None)
        src_times = [i.source_time for i in inputs if i.source_time]
        return inputs, SourceStatus(
            adapter=self.name,
            label=self.label,
            status="ok" if inputs else "empty",
            detail=None if inputs else "source responded with no records for this place/time",
            fetched_at=fetched,
            source_time=max(src_times) if src_times else None,
            urls=self._urls,
            n_inputs=len(inputs),
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
        )


def utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def iso_z(dt: datetime) -> str:
    return utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def floor_hour(dt: datetime) -> datetime:
    return utc(dt).replace(minute=0, second=0, microsecond=0)


def is_historical(as_of: datetime, slack: timedelta = timedelta(hours=2)) -> bool:
    return utc(as_of) < datetime.now(timezone.utc) - slack
