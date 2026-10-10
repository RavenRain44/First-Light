from datetime import timedelta

from backend.app.engine import ThresholdRegistry, evaluate
from backend.app.models import Posture


def test_warning_during_arrival_delays_when_it_clears(facility, fixed_now, bundle_factory):
    bundle = bundle_factory(
        facility,
        fixed_now,
        ice=0.31,
        event="Ice Storm Warning",
        onset_hours=3,
        duration_hours=4,
    )
    result = evaluate(facility, bundle, fixed_now, ThresholdRegistry.load())
    assert result.posture == Posture.DELAYED_ARRIVAL
    assert result.delay_hours is not None
    assert {item.id for item in result.thresholds_crossed} >= {
        "ice_accum_ge_0_10in",
        "ice_accum_ge_0_25in",
    }
    assert result.inputs[0].sha256 == bundle.items[0].sha256
    assert result.what_would_change


def test_extreme_threshold_forces_closure(facility, fixed_now, bundle_factory):
    bundle = bundle_factory(facility, fixed_now, ice=0.55, event="Winter Weather Advisory")
    result = evaluate(facility, bundle, fixed_now, ThresholdRegistry.load())
    assert result.posture == Posture.CLOSED


def test_life_safety_alert_adds_shelter_overlay(facility, fixed_now, bundle_factory):
    bundle = bundle_factory(
        facility,
        fixed_now,
        event="Tornado Warning",
        onset_hours=-0.5,
        duration_hours=1,
    )
    result = evaluate(facility, bundle, fixed_now, ThresholdRegistry.load())
    assert result.shelter_now is True


def test_injected_time_is_deterministic(facility, fixed_now, bundle_factory):
    bundle = bundle_factory(facility, fixed_now, ice=0.31, event="Ice Storm Warning")
    registry = ThresholdRegistry.load()
    first = evaluate(facility, bundle, fixed_now, registry)
    second = evaluate(facility, bundle, fixed_now, registry)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    later = evaluate(facility, bundle, fixed_now + timedelta(days=1), registry)
    assert later.posture != first.posture
