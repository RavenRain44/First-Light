from __future__ import annotations

from backend.app.db.repository import Repository
from backend.app.db.session import build_session_factory
from backend.app.sample_data import FACILITIES, seeded_employees


def test_seed_inserts_facilities_before_employees_with_foreign_keys_enabled() -> None:
    repository = Repository(build_session_factory("sqlite://"))

    employees = seeded_employees()
    repository.seed(FACILITIES, employees)

    assert len(repository.list_facilities()) == len(FACILITIES)
    assert sum(len(repository.employees_for_facility(item.id)) for item in FACILITIES) == len(
        employees
    )

