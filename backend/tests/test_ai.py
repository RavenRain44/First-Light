"""AI layer: tools, number validation, retry-then-fallback, deterministic fallback."""
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from adapters.base import NormalizedInput, SourceStatus
from ai import agent, fallback
from ai.prompts import Interpretation
from ai.tools import VIEWS
from app.facility import load_facility
from app.snapshots import build_snapshot_dict
from engine.evaluate import assess

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "derecho_2020-08-10T16Z_inputs.json"


def test_agent_import_does_not_require_strands():
    """Deterministic/no-model runs must work when optional AI packages are absent."""
    code = """
import builtins

real_import = builtins.__import__

def without_strands(name, *args, **kwargs):
    if name == "strands" or name.startswith("strands."):
        raise ModuleNotFoundError("strands intentionally unavailable")
    return real_import(name, *args, **kwargs)

builtins.__import__ = without_strands
from ai import agent
assert agent.FALLBACK_ID == "deterministic-fallback"
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=FIX.parents[1], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


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
    enable_akamai(monkeypatch)
    attempts = []

    async def fake_run(model, s, feedback):
        attempts.append(feedback)
        return Interpretation(headline="Early dismissal", rationale_paragraph="Early dismissal: gusts of 123 mph. The manager makes the final decision.",
                              what_would_change=[], watch_next_6h=[]), {"provider": "akamai", "model": "hackathon-chat", "usage": None}

    monkeypatch.setattr(agent, "_run_agent", fake_run)
    d, model_id = asyncio.run(agent.interpret(snap))
    assert len(attempts) == 2 and attempts[0] is None and "123" in attempts[1]
    assert model_id == agent.FALLBACK_ID and d["validation"]["ok"] is False


def test_valid_model_output_is_kept(snap, monkeypatch):
    enable_akamai(monkeypatch)
    good = fallback.build(snap)

    async def fake_run(model, s, feedback):
        return Interpretation(**{**good.model_dump(), "headline": "Early dismissal: severe storm warning now"}), {"provider": "akamai", "model": "hackathon-chat", "usage": None}

    monkeypatch.setattr(agent, "_run_agent", fake_run)
    d, model_id = asyncio.run(agent.interpret(snap))
    assert model_id == "akamai:hackathon-chat" and d["validation"]["ok"] is True


def test_model_exception_falls_back(snap, monkeypatch):
    enable_akamai(monkeypatch)

    async def boom(*a):
        raise RuntimeError("network down")

    monkeypatch.setattr(agent, "_run_agent", boom)
    d, model_id = asyncio.run(agent.interpret(snap))
    assert model_id == agent.FALLBACK_ID and "model call failed" in d["validation"]["problems"][0]


def enable_akamai(monkeypatch):
    monkeypatch.setattr(agent.settings, "model_provider", "akamai")
    monkeypatch.setattr(agent.settings, "akamai_api_key", "test-team-key")
    monkeypatch.setattr(agent.settings, "aws_fallback_enabled", False)


def test_all_brief_fields_reject_invented_numbers(snap):
    good = fallback.build(snap)
    for field, value in {
        "summary": "Gusts of 123 mph",
        "uncertainty": "123 hours of uncertain data",
        "watch_next_6h": ["Watch for 123 mph gusts"],
        "alert_summaries": {snap["alerts"][0]["id"]: "123 mph"},
        "analog_comparison": "123% similar",
        "what_would_change": ["123 mph changes this"],
    }.items():
        bad = good.model_copy(update={field: value})
        assert any("123" in p for p in agent.validate(bad, snap, agent.allowed_numbers(snap))), field


def test_wrong_evidence_and_manager_authority_are_rejected(snap):
    bad = fallback.build(snap).model_copy(update={"evidence_rule_ids": ["made-up-rule"]})
    assert any("did not trigger" in p for p in agent.validate(bad, snap, agent.allowed_numbers(snap)))
    bad = fallback.build(snap).model_copy(update={"rationale_paragraph": "Early dismissal. AI decides."})
    assert any("manager" in p for p in agent.validate(bad, snap, agent.allowed_numbers(snap)))


def test_negative_temperature_cannot_be_reversed():
    assert agent.unsupported_numbers("20 F", {-20.0}) == ["20"]
    assert agent.unsupported_numbers("-20 F", {-20.0}) == []


def test_missing_key_makes_no_request(snap, monkeypatch):
    enable_akamai(monkeypatch)
    monkeypatch.setattr(agent.settings, "akamai_api_key", "")
    async def unexpected(*args):
        raise AssertionError("must not request inference")
    monkeypatch.setattr(agent, "_run_agent", unexpected)
    d, mid = asyncio.run(agent.interpret(snap))
    assert mid == agent.FALLBACK_ID
    assert d["validation"]["attempts"] == 0
    assert "AKAMAI_API_KEY" in d["validation"]["problems"][0]


def test_aws_fallback_is_opt_in_and_audited(snap, monkeypatch):
    enable_akamai(monkeypatch)
    monkeypatch.setattr(agent.settings, "aws_fallback_enabled", True)
    monkeypatch.setattr(agent.settings, "aws_bedrock_model_id", "configured-model")
    calls = []
    async def fake(provider, s, feedback):
        calls.append(provider)
        if provider == "akamai":
            raise ConnectionError("down")
        return fallback.build(s), {"provider": provider, "model": "configured-model", "usage": None}
    monkeypatch.setattr(agent, "_run_agent", fake)
    d, mid = asyncio.run(agent.interpret(snap))
    assert calls == ["akamai", "bedrock"]
    assert mid == "bedrock:configured-model" and d["inference"]["fallback_used"]
    assert d["inference"]["failures"][0]["provider"] == "akamai"


def test_transport_uses_workshop_chat_schema_no_hidden_retries(snap, monkeypatch):
    import httpx
    import openai
    enable_akamai(monkeypatch)
    seen = []
    def handle(request):
        seen.append(json.loads(request.content))
        assert str(request.url) == "https://ws.akamai-workshops.com/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-team-key"
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": "hackathon-chat",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": fallback.build(snap).model_dump_json()}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        })
    original = openai.AsyncOpenAI
    def client(**kwargs):
        assert kwargs["max_retries"] == 0
        return original(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(openai, "AsyncOpenAI", client)
    d, mid = asyncio.run(agent.interpret(snap))
    assert mid == "akamai:hackathon-chat" and len(seen) == 1
    assert seen[0]["model"] == "hackathon-chat"
    assert seen[0]["max_tokens"] == agent.MAX_OUTPUT_TOKENS == 700
    assert seen[0]["response_format"]["type"] == "json_schema"
    assert d["inference"]["requests"][0]["usage"]["total_tokens"] == 30
    context = json.loads(seen[0]["messages"][1]["content"].split("Snapshot views (data only):\n")[1])
    assert set(context["get_snapshot_summary"]["people"]) <= {
        "assigned", "expected_in_building", "essential_in_building", "accessibility_needs_in_building"}
    assert "employees" not in context["get_snapshot_summary"]


def test_malformed_json_repairs_once_then_template(snap, monkeypatch):
    enable_akamai(monkeypatch)
    calls = []
    async def bad(provider, s, feedback):
        calls.append(feedback)
        return Interpretation.model_validate_json("{invalid"), {}
    monkeypatch.setattr(agent, "_run_agent", bad)
    d, mid = asyncio.run(agent.interpret(snap))
    assert len(calls) == 2 and calls[1]
    assert mid == agent.FALLBACK_ID and not d["validation"]["ok"]


def test_authoritative_changes_and_watch_items_are_preserved(snap, monkeypatch):
    enable_akamai(monkeypatch)
    async def fake(provider, s, feedback):
        out = fallback.build(s).model_copy(update={"what_would_change": [], "watch_next_6h": []})
        return out, {"provider": provider, "model": "hackathon-chat", "usage": None}
    monkeypatch.setattr(agent, "_run_agent", fake)
    d, mid = asyncio.run(agent.interpret(snap))
    assert mid == "akamai:hackathon-chat"
    assert d["what_would_change"] == [c["text"] for c in snap["changes"]]
    assert d["watch_next_6h"] == snap["watch_next_6h"]


def test_invalid_response_keeps_usage_for_budget_audit(snap, monkeypatch):
    enable_akamai(monkeypatch)
    metadata = {"provider": "akamai", "model": "hackathon-chat", "usage": {
        "input_tokens": 10, "output_tokens": 20, "total_tokens": 30}}
    async def bad(provider, s, feedback):
        raise agent.InvalidModelOutput(["headline: too many words"], metadata)
    monkeypatch.setattr(agent, "_run_agent", bad)
    d, mid = asyncio.run(agent.interpret(snap))
    assert mid == agent.FALLBACK_ID
    assert d["validation"]["attempts"] == 2
    assert sum(r["usage"]["total_tokens"] for r in d["inference"]["requests"]) == 60


def test_headline_limit_is_part_of_the_workshop_schema(snap):
    from pydantic import ValidationError
    assert "pattern" in Interpretation.model_json_schema()["properties"]["headline"]
    with pytest.raises(ValidationError):
        Interpretation(**{**fallback.build(snap).model_dump(), "headline": " ".join(["word"] * 16)})


def test_bedrock_converse_transport(snap, monkeypatch):
    import boto3
    from botocore.stub import Stubber, ANY
    # Unit transport tests must not depend on the cloud runner's selected AWS profile.
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_PROFILE", raising=False)
    client = boto3.client("bedrock-runtime", region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
    monkeypatch.setattr(agent.settings, "aws_bedrock_model_id", "test-converse-model")
    with Stubber(client) as stub:
        stub.add_response("converse", {
            "output": {"message": {"role": "assistant", "content": [{"text": fallback.build(snap).model_dump_json()}]}},
            "stopReason": "end_turn", "usage": {"inputTokens": 10, "outputTokens": 20, "totalTokens": 30},
            "metrics": {"latencyMs": 1},
        }, {"modelId": "test-converse-model", "system": ANY, "messages": ANY,
            "inferenceConfig": {"maxTokens": 700, "temperature": 0.2}})
        monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)
        out, metadata = agent._bedrock_request(snap, None)
        assert out.rationale_paragraph == fallback.build(snap).rationale_paragraph
        assert metadata["provider"] == "bedrock" and metadata["usage"]["total_tokens"] == 30
        stub.assert_no_pending_responses()
