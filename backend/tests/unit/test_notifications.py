from backend.app.engine import ThresholdRegistry, evaluate
from backend.app.notify.messages import check_message
from backend.app.notify.resolver import build_notification_package
from backend.app.sample_data import seeded_employees


def test_every_employee_has_reason_and_edge_cases_are_explainable(
    facility, fixed_now, bundle_factory
):
    recommendation = evaluate(
        facility,
        bundle_factory(facility, fixed_now, ice=0.55, event="Ice Storm Warning"),
        fixed_now,
        ThresholdRegistry.load(),
    )
    roster = [item for item in seeded_employees() if item.home_facility_id == facility.id]
    package = build_notification_package(facility, roster, recommendation, fixed_now)
    assert len(package.recipients) == len(roster)
    assert all(item.reason for item in package.recipients)
    assert any(item.variant == "essential" for item in package.recipients)
    assert any(not item.included and "leave" in item.reason for item in package.recipients)
    assert any(not item.included and "detail" in item.reason for item in package.recipients)
    hearing = next(item for item in package.recipients if item.employee_id == "emp-008")
    assert "voice" not in hearing.channels
    assert package.checklist_valid


def test_message_checker_rejects_missing_elements():
    errors = check_message("Facility closed", "Go home")
    assert errors
    assert any("required element" in error for error in errors)
