import pytest

from backend.app.engine import ThresholdRegistry, evaluate
from backend.app.llm.client import UnavailableLLMClient
from backend.app.llm.grounding import verify_grounding
from backend.app.llm.service import DraftingService


def test_grounding_rejects_invented_number():
    grounded, errors = verify_grounding(
        "The wind will reach 91 mph.",
        {"wind_gust_mph": 58, "posture": "CLOSED"},
    )
    assert grounded is False
    assert "91mph" in errors[0]


@pytest.mark.asyncio
async def test_drafting_falls_back_when_inference_is_down(facility, fixed_now, bundle_factory):
    recommendation = evaluate(
        facility,
        bundle_factory(facility, fixed_now, ice=0.31, event="Ice Storm Warning"),
        fixed_now,
        ThresholdRegistry.load(),
    )
    text, call = await DraftingService(UnavailableLLMClient()).rationale(recommendation)
    assert text == recommendation.rationale_template
    assert call.used_fallback
