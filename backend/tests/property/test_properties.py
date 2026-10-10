from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from backend.app.engine import ThresholdRegistry, evaluate
from backend.app.models import POSTURE_RANK
from backend.app.sample_data import FACILITIES
from backend.tests.conftest import make_bundle


@given(
    lower=st.floats(min_value=0, max_value=0.6, allow_nan=False, allow_infinity=False),
    extra=st.floats(min_value=0, max_value=0.5, allow_nan=False, allow_infinity=False),
)
def test_worse_ice_never_yields_milder_posture(lower, extra):
    facility = FACILITIES[0]
    fixed_now = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
    registry = ThresholdRegistry.load()
    mild = evaluate(
        facility,
        make_bundle(facility, fixed_now, ice=lower, event="Winter Weather Advisory"),
        fixed_now,
        registry,
    )
    worse = evaluate(
        facility,
        make_bundle(facility, fixed_now, ice=lower + extra, event="Winter Weather Advisory"),
        fixed_now,
        registry,
    )
    assert POSTURE_RANK[worse.posture] >= POSTURE_RANK[mild.posture]
