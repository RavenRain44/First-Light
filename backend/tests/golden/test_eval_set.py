import pytest

from backend.app.evals import evaluate_scenario, load_scenarios


@pytest.mark.parametrize("scenario", load_scenarios(), ids=lambda item: item["id"])
def test_recorded_eval_scenario(scenario):
    result = evaluate_scenario(scenario)
    assert result.posture.value == scenario["expected_posture"]
    assert result.shelter_now == scenario.get("expected_shelter", False)
    assert result.rationale_grounded
    assert result.inputs
