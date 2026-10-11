"""New notification inference uses the same Akamai protocol and failure boundaries as briefs."""
import asyncio
import json

import httpx
import openai
import pytest

from ai import agent


@pytest.fixture
def workshop(monkeypatch):
    monkeypatch.setattr(agent.settings, "model_provider", "akamai")
    monkeypatch.setattr(agent.settings, "akamai_api_key", "test-team-key")
    seen = []
    reply = {"explanation": "Extreme winter hazards are present."}
    config = {"status": 200, "finish_reason": "stop"}
    original = openai.AsyncOpenAI

    def handle(request):
        body = json.loads(request.content)
        seen.append(body)
        assert str(request.url) == "https://ws.akamai-workshops.com/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-team-key"
        if config["status"] != 200:
            return httpx.Response(config["status"], json={"error": {"message": "test error", "type": "test"}})
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": "hackathon-chat",
            "choices": [{"index": 0, "finish_reason": config["finish_reason"], "message": {
                "role": "assistant", "content": config.get("content", json.dumps(reply))}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        })

    def client(**kwargs):
        assert kwargs["max_retries"] == 0 and kwargs["timeout"] == 30
        return original(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(openai, "AsyncOpenAI", client)
    return seen, reply, config


def generate():
    return asyncio.run(agent.hazard_sentence("Describe weather only.", '["winter: extreme"]'))


def test_notification_workshop_schema_and_usage(workshop):
    seen, _, _ = workshop
    wording, model, inference = generate()
    assert wording == "Extreme winter hazards are present."
    assert model == "akamai:hackathon-chat"
    assert inference["provider"] == "akamai" and not inference["fallback_used"]
    assert inference["requests"][0]["usage"]["total_tokens"] == 30
    assert len(seen) == 1 and seen[0]["model"] == "hackathon-chat"
    assert seen[0]["max_tokens"] == 200
    assert seen[0]["response_format"]["type"] == "json_schema"
    schema = seen[0]["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["explanation"]["maxLength"] == 350


def test_staff_email_draft_uses_strict_akamai_schema(workshop):
    seen, reply, _ = workshop
    reply.clear()
    reply["body"] = "Team, severe winter risk supports the recorded closure."
    context = {"risk_recommendation": {"posture": "CLOSED", "risk_level": "Closed"},
               "recorded_decision": {"decided_by": "Manager", "posture": "CLOSED"}}
    body, model, inference = asyncio.run(agent.draft_staff_email(context))
    assert body == reply["body"]
    assert model == "akamai:hackathon-chat"
    assert inference["provider"] == "akamai" and not inference["fallback_used"]
    request = seen[0]
    assert request["model"] == "hackathon-chat" and request["max_tokens"] == 500
    assert request["response_format"]["json_schema"]["name"] == "staff_email_draft"
    schema = request["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["body"]["maxLength"] == 1600
    assert json.dumps(context) in request["messages"][1]["content"]


def test_staff_email_draft_requires_akamai(workshop, monkeypatch):
    seen, _, _ = workshop
    monkeypatch.setattr(agent.settings, "model_provider", "none")
    body, model, inference = asyncio.run(agent.draft_staff_email({}))
    assert body is None and model == agent.FALLBACK_ID
    assert seen == [] and inference["failures"]


def test_staff_email_and_sms_drafts_use_strict_akamai_schema(workshop):
    seen, reply, _ = workshop
    reply.clear()
    reply.update({
        "email_body": "Team, the recorded closure reflects today's severe winter risk.",
        "sms_intro": "Manager confirms closure as severe winter risk remains.",
    })
    context = {"risk_recommendation": {"posture": "CLOSED", "risk_level": "Closed"},
               "recorded_decision": {"decided_by": "Manager", "posture": "CLOSED"}}
    drafts, model, inference = asyncio.run(agent.draft_staff_notifications(context))
    assert drafts == reply
    assert model == "akamai:hackathon-chat"
    assert inference["provider"] == "akamai" and not inference["fallback_used"]
    request = seen[0]
    assert request["response_format"]["json_schema"]["name"] == "staff_notification_drafts"
    schema = request["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["sms_intro"]["maxLength"] == 120
    assert json.dumps(context) in request["messages"][1]["content"]


def test_staff_notification_drafts_reject_sms_over_120_characters(workshop):
    seen, reply, _ = workshop
    reply.clear()
    reply.update({"email_body": "A complete email sentence.", "sms_intro": "x" * 121})
    drafts, model, inference = asyncio.run(agent.draft_staff_notifications({}))
    assert drafts is None and model == agent.FALLBACK_ID
    assert seen and inference["failures"]


@pytest.mark.parametrize("text", [
    "Closing is advised due to weather.", "Delayed arrival is advised.",
    "Employees may resume operations.", "The facility is safe.",
    "Wind gusts reach 97 mph.", "Extreme winter hazards. Go home.", " ",
])
def test_notification_rejects_numbers_instructions_and_multiple_sentences(workshop, text):
    seen, reply, _ = workshop
    reply["explanation"] = text
    wording, model, inference = generate()
    assert wording is None and model == agent.FALLBACK_ID
    assert len(seen) == 1  # No paid repair loop for notification wording.
    assert inference["provider"] == "template" and inference["failures"]
    assert inference["requests"][0]["usage"]["total_tokens"] == 30


@pytest.mark.parametrize("content,finish", [
    ('{"explanation":"Extreme winter hazards are present."}', "length"),
    ("{}", "stop"), ("not JSON", "stop"),
    ('{"explanation":"Winter hazards.","decision":"CLOSED"}', "stop"),
])
def test_notification_rejects_incomplete_or_malformed_responses(workshop, content, finish):
    seen, _, config = workshop
    config.update(content=content, finish_reason=finish)
    wording, _, inference = generate()
    assert wording is None and len(seen) == 1 and inference["failures"]
    assert inference["requests"][0]["usage"]["total_tokens"] == 30


@pytest.mark.parametrize("status", [401, 429, 503])
def test_notification_provider_failure_does_not_retry(workshop, status):
    seen, _, config = workshop
    config["status"] = status
    wording, _, inference = generate()
    assert wording is None and len(seen) == 1
    assert inference["provider"] == "template" and inference["failures"]
    assert "test-team-key" not in json.dumps(inference)


@pytest.mark.parametrize("provider,key", [("none", "test-team-key"), ("akamai", ""), ("openai", "test-team-key")])
def test_notification_disabled_or_missing_key_never_calls_model(workshop, monkeypatch, provider, key):
    seen, _, _ = workshop
    monkeypatch.setattr(agent.settings, "model_provider", provider)
    monkeypatch.setattr(agent.settings, "akamai_api_key", key)
    wording, _, inference = generate()
    assert wording is None and seen == [] and inference["requests"] == []
