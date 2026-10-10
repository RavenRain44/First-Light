"""AI layer: tools, number validation, retry-then-fallback, deterministic fallback."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from adapters.base import NormalizedInput, SourceStatus
from ai import agent, fallback
from ai.prompts import Interpretation
from ai.tools import VIEWS, build_tools
from app.facility import load_facility
from app.snapshots import build_snapshot_dict
from engine.evaluate import assess

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "derecho_2020-08-10T16Z_inputs.json"


@pytest.fixture(scope="module")
def snap():
    d = json.loads(FIX.read_text(encoding="utf-8"))
    inputs = [NormalizedInput(**i) for i in d["inputs"]]
    statuses = [SourceStatus(**s) for s in d["statuses"]]
    fac = load_facility()
    a = assess(inputs, statuses, fac, datetime(2020, 8, 10, 16, tzinfo=timezone.utc), "replay")
    return build_snapshot_dict(fac, a, inputs, statuses, "replay")


def test_tool_views_are_json_and_local_time(snap):
    for name, fn in VIEWS.items():
        json.dumps(fn(snap), default=str)
    s = VIEWS["get_snapshot_summary"](snap)
    assert s["recommended_posture"] == "EARLY_DISMISSAL"
    assert "CDT" in s["as_of_local"]
    assert VIEWS["get_triggered_rules"](snap)["triggered"]


def test_strands_tools_build_with_specs(snap):
    calls = []
    tools = build_tools(snap, calls)
    names = {t.tool_name for t in tools}
    assert names == set(VIEWS)
    assert all(t.tool_spec["description"] for t in tools)


def test_fallback_is_complete_and_numbers_validate(snap):
    interp = fallback.build(snap)
    assert "Early Dismissal" in interp.rationale_paragraph
    assert "Severe Thunderstorm Warning" in interp.rationale_paragraph
    assert len(interp.headline.split()) <= 15
    assert agent.validate(interp, snap, agent.allowed_numbers(snap)) == []


def test_validation_rejects_invented_numbers_and_posture(snap):
    allowed = agent.allowed_numbers(snap)
    bad = Interpretation(headline="Early dismissal today", rationale_paragraph=(
        "Recommend early dismissal. Gusts of 97 mph are expected at 11:00 CDT."), what_would_change=[], watch_next_6h=[])
    probs = agent.validate(bad, snap, allowed)
    assert any("97" in p for p in probs)
    wrong = Interpretation(headline="Close", rationale_paragraph="We recommend CLOSED for the facility.",
                           what_would_change=[], watch_next_6h=[])
    assert any("posture" in p or "recommends" in p for p in agent.validate(wrong, snap, allowed))


def test_rounded_copies_of_snapshot_numbers_pass():
    allowed = {58.3, 0.254}
    assert agent.unsupported_numbers("gusts near 58 mph and 0.25 in of ice", allowed) == []
    assert agent.unsupported_numbers("gusts near 59 mph", allowed) == ["59"]


def test_no_credentials_uses_fallback(snap, monkeypatch):
    monkeypatch.setattr(agent.settings, "model_provider", "none")
    d, model_id = asyncio.run(agent.interpret(snap))
    assert model_id == agent.FALLBACK_ID and d["rationale_paragraph"]


def test_retry_once_then_fallback(snap, monkeypatch):
    monkeypatch.setattr(agent, "build_model", lambda: (object(), "fake:model"))
    attempts = []

    async def fake_run(model, s, feedback):
        attempts.append(feedback)
        return Interpretation(headline="Early dismissal", rationale_paragraph="Early dismissal: gusts of 123 mph.",
                              what_would_change=[], watch_next_6h=[]), ["get_snapshot_summary"]

    monkeypatch.setattr(agent, "_run_agent", fake_run)
    d, model_id = asyncio.run(agent.interpret(snap))
    assert len(attempts) == 2 and attempts[0] is None and "123" in attempts[1]
    assert model_id == agent.FALLBACK_ID and d["validation"]["ok"] is False


def test_valid_model_output_is_kept(snap, monkeypatch):
    monkeypatch.setattr(agent, "build_model", lambda: (object(), "fake:model"))
    good = fallback.build(snap)

    async def fake_run(model, s, feedback):
        return Interpretation(**{**good.model_dump(), "headline": "Early dismissal: severe storm warning now"}), ["get_snapshot_summary"]

    monkeypatch.setattr(agent, "_run_agent", fake_run)
    d, model_id = asyncio.run(agent.interpret(snap))
    assert model_id == "fake:model" and d["validation"]["ok"] is True


def test_model_exception_falls_back(snap, monkeypatch):
    monkeypatch.setattr(agent, "build_model", lambda: (object(), "fake:model"))

    async def boom(*a):
        raise RuntimeError("network down")

    monkeypatch.setattr(agent, "_run_agent", boom)
    d, model_id = asyncio.run(agent.interpret(snap))
    assert model_id == agent.FALLBACK_ID and "model call failed" in d["validation"]["problems"][0]


def test_agent_constructs_with_real_strands_model(snap, monkeypatch):
    """Wiring check without a network call: Strands Agent + Anthropic provider + our tools."""
    from strands import Agent
    from strands.models.anthropic import AnthropicModel
    m = AnthropicModel(client_args={"api_key": "test"}, model_id="claude-sonnet-5-5", max_tokens=100)
    a = Agent(model=m, system_prompt="x", tools=build_tools(snap, []), callback_handler=None)
    assert set(a.tool_names) == set(VIEWS)
