"""New notification inference uses the same Akamai protocol and failure boundaries as briefs."""
import asyncio
import json

import httpx
import pytest

from ai import agent


@pytest.fixture
def workshop(monkeypatch):
    monkeypatch.setattr(agent.settings, "model_provider", "akamai")
    monkeypatch.setattr(agent.settings, "akamai_api_key", "test-team-key")
    seen = []
    reply = {"explanation": "Extreme winter hazards are present."}
    config = {"status": 200, "finish_reason": "stop"}
    original = httpx.AsyncClient

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
        assert kwargs["timeout"] == 30
        return original(**kwargs, transport=httpx.MockTransport(handle))
    monkeypatch.setattr(httpx, "AsyncClient", client)
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
