"""Shared test setup."""
import pytest

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
