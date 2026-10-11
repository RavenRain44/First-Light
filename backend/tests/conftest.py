"""Shared test setup."""
import pytest
from datetime import datetime, timezone

from app import storage
from app.config import settings


@pytest.fixture(autouse=True)
def no_real_object_storage(monkeypatch):
    """Tests never touch a real bucket, even when the developer's .env has OBJ_* keys.
    Storage tests install their own in-memory bucket."""
    monkeypatch.setattr(settings, "obj_bucket", "")
    storage.set_bucket(None)
    yield
    storage.set_bucket(None)


@pytest.fixture
def cached_live_storm(monkeypatch):
    """Live demonstration fixture for authority/storage tests, using saved storm evidence.

    These tests exercise recording a live demo decision, not replay permission.
    No real weather provider or inference request is needed.
    """
    from adapters.base import demo_reference_time
    from app import snapshots
    original_gather = snapshots.gather
    async def demo_time(facility):
        return datetime(2020, 8, 10, 16, tzinfo=timezone.utc)
    async def saved_evidence(facility, as_of, mode):
        token = demo_reference_time.set(None)
        try:
            return await original_gather(facility, as_of, "replay" if mode == "live" else mode)
        finally:
            demo_reference_time.reset(token)
    monkeypatch.setattr(snapshots, "demo_live_as_of", demo_time)
    monkeypatch.setattr(snapshots, "gather", saved_evidence)
