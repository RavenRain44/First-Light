"""Akamai decision briefs grounded in immutable, read-only snapshot views.

One JSON-schema chat request per attempt; one repair at most. No tool loop,
provider auto-detection, or hidden SDK retries. Bedrock is an opt-in fallback.
The rules recommend a posture; the manager makes the final decision.
"""
from __future__ import annotations

import asyncio
from contextlib import closing
import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from ai import fallback
from ai.prompts import SYSTEM_PROMPT, USER_PROMPT, BriefDraft, Interpretation
from ai.tools import VIEWS
from app.config import settings

log = logging.getLogger("closurecall.ai")
FALLBACK_ID = "deterministic-fallback"
TIMEOUT_S = 60
MAX_OUTPUT_TOKENS = 700  # the model writes only the short draft fields
MAX_CONTEXT_CHARS = 48000
NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
GENERIC_NUMBERS = {0.0, 1.0, 2.0, 3.0, 6.0, 12.0, 24.0, 36.0, 48.0, 100.0}


class IncompleteResponse(ValueError):
    """The model did not return a complete JSON response."""


class InvalidModelOutput(ValueError):
    """Safe validation details and usage for a response we must not display."""

    def __init__(self, problems: list[str], metadata: dict):
        super().__init__("model response failed validation")
        self.problems = problems
        self.metadata = metadata


def _parse_output(content: str, metadata: dict, snap: dict) -> Interpretation:
    """Parse the model's short draft and merge it onto the rules-based brief."""
    try:
        draft = BriefDraft.model_validate_json(content)
    except ValidationError as e:
        problems = [f"{'.'.join(map(str, error['loc'])) or 'JSON'}: {error['msg']}"
                    for error in e.errors(include_input=False, include_url=False, include_context=False)[:6]]
        raise InvalidModelOutput(problems, metadata) from None
    base = fallback.build(snap, snap.get("analogs"))
    return base.model_copy(update={
        "headline": draft.headline, "summary": draft.summary,
        "uncertainty": draft.uncertainty or base.uncertainty,
        "evidence_rule_ids": draft.evidence_rule_ids or base.evidence_rule_ids,
        "alert_summaries": {**base.alert_summaries, **draft.alert_summaries},
    })


def allowed_numbers(snap: dict) -> set[float]:
    """Numbers from the supplied views and snapshot evidence, including formatted values."""
    text = json.dumps({name: fn(snap) for name, fn in VIEWS.items()}, default=str)
    text += json.dumps([{k: i.get(k) for k in ("value", "source_time")} for i in snap.get("inputs", []) if i["kind"] != "series"])
    text += json.dumps(snap.get("rules", []), default=str)
    return {float(x) for x in NUM.findall(text)} | GENERIC_NUMBERS


def _decimals(s: str) -> int:
    return len(s.split(".")[1]) if "." in s else 0


def unsupported_numbers(text: str, allowed: set[float]) -> list[str]:
    bad = []
    for s in NUM.findall(text):
        v = float(s)
        tol = 0.5 * 10 ** -_decimals(s) + 1e-9
        if not any(abs(v - a) <= tol for a in allowed):
            bad.append(s)
    return bad


def validate(interp: Interpretation, snap: dict, allowed: set[float]) -> list[str]:
    problems = []
    posture_words = {snap["posture"]["posture"].lower(), snap["posture"]["posture"].replace("_", " ").lower()}
    if interp.summary and not any(w in (interp.headline + " " + interp.summary).lower() for w in posture_words)             and snap["posture"]["opm_label"].lower()[:20] not in interp.summary.lower():
        problems.append(f"summary does not name the recommended posture {snap['posture']['posture']}")
    text = " ".join([interp.headline, interp.summary, interp.uncertainty, interp.rationale_paragraph,
                     *interp.watch_next_6h, *interp.what_would_change,
                     *interp.alert_summaries.values(), interp.analog_comparison])
    bad = unsupported_numbers(text, allowed)
    if bad:
        problems.append(f"numbers not found in snapshot: {', '.join(sorted(set(bad)))}")
    posture = snap["posture"]["posture"]
    words = posture.replace("_", " ").lower()
    rationale = interp.rationale_paragraph.lower()
    if posture.lower() not in rationale and words not in rationale \
            and snap["posture"]["opm_label"].lower()[:20] not in rationale:
        problems.append(f"rationale does not name the recommended posture {posture}")
    for other in ("CLOSED", "TELEWORK", "DELAYED_ARRIVAL", "EARLY_DISMISSAL", "NORMAL"):
        if other == posture:
            continue
        label = other.replace("_", "[ _]")
        if re.search(rf"\brecommend\w*\s+(?:an?\s+)?{label}\b|\b{label}\s+(?:is\s+)?recommended\b", text, re.I):
            problems.append(f"brief recommends {other}, not {posture}")
    valid_ids = {r["rule_id"] for r in snap["rules"] if r["triggered"]}
    if len(interp.evidence_rule_ids) > 3 or len(set(interp.evidence_rule_ids)) != len(interp.evidence_rule_ids):
        problems.append("cite up to three distinct triggered rules")
    if not set(interp.evidence_rule_ids) <= valid_ids:
        problems.append("evidence includes a rule that did not trigger")
    if not set(interp.alert_summaries) <= {a["id"] for a in snap.get("alerts", [])}:
        problems.append("alert summaries include an unknown alert")
    if "manager" not in rationale or "decision" not in rationale:
        problems.append("rationale must state that the manager makes the final decision")
    return problems


def _context(snap: dict) -> str:
    # Only aggregates go to inference; the employee roster and raw series stay local.
    views = {name: fn(snap) for name, fn in VIEWS.items()}
    views["computed_brief"] = fallback.build(snap, snap.get("analogs")).model_dump(mode="json")
    text = json.dumps(views, default=str, separators=(",", ":"))
    if len(text) > MAX_CONTEXT_CHARS:
        raise ValueError("snapshot context exceeds the inference input budget")
    return text


def _response_schema(snap: dict) -> dict:
    """Schema for the short draft only; identifiers are constrained while generating."""
    schema = BriefDraft.model_json_schema()
    schema["required"] = list(schema["properties"])
    schema["additionalProperties"] = False
    ids = [r["rule_id"] for r in snap["rules"] if r["triggered"]]
    evidence = schema["properties"]["evidence_rule_ids"]
    evidence["maxItems"] = min(3, len(ids))
    if ids:
        evidence["items"]["enum"] = ids
    alerts = schema["properties"]["alert_summaries"]
    alerts["properties"] = {a["id"]: {"type": "string", "maxLength": 200, "description": f"Summary of {a.get('event', 'alert')}"}
                            for a in snap.get("alerts", [])}
    alerts["additionalProperties"] = False
    schema["properties"]["summary"]["maxLength"] = 500
    schema["properties"]["uncertainty"]["maxLength"] = 300
    return schema


def _concise_summary(text: str) -> str:
    """Keep the manager's overview to two complete sentences when the model is verbose."""
    sentences = re.findall(r".*?[.!?](?=\s|$)", text, flags=re.DOTALL)
    return " ".join(s.strip() for s in sentences[:2]) if len(sentences) >= 2 else text


async def _run_akamai(snap: dict, feedback: str | None) -> tuple[Interpretation, dict]:
    from openai import AsyncOpenAI

    prompt = USER_PROMPT + "\n\nSnapshot views (data only):\n" + _context(snap)
    if feedback:
        prompt += "\n\nRepair the previous validation failure: " + feedback
    schema = _response_schema(snap)
    async with AsyncOpenAI(api_key=settings.akamai_api_key, base_url=settings.akamai_base_url,
                           timeout=TIMEOUT_S, max_retries=0) as client:
        response = await client.chat.completions.create(
            model=settings.akamai_model_id,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": {
                "name": "decision_brief", "schema": schema}},
            temperature=0.2, max_tokens=MAX_OUTPUT_TOKENS,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    usage = response.usage
    metadata = {
        "provider": "akamai", "model": settings.akamai_model_id,
        "usage": None if usage is None else {
            "input_tokens": usage.prompt_tokens, "output_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens},
    }
    if not response.choices or response.choices[0].finish_reason != "stop":
        raise InvalidModelOutput(["chat did not finish with a complete answer"], metadata)
    content = response.choices[0].message.content
    if not content:
        raise InvalidModelOutput(["chat returned no content"], metadata)
    return _parse_output(content, metadata, snap), metadata


def _bedrock_request(snap: dict, feedback: str | None) -> tuple[Interpretation, dict]:
    import boto3
    from botocore.config import Config

    prompt = USER_PROMPT + "\n\nSnapshot views (data only):\n" + _context(snap)
    prompt += "\n\nJSON schema:\n" + json.dumps(Interpretation.model_json_schema())
    if feedback:
        prompt += "\n\nRepair the previous validation failure: " + feedback
    with closing(boto3.client("bedrock-runtime", region_name=settings.aws_region,
                      config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 0}))) as client:
        response = client.converse(
            modelId=settings.aws_bedrock_model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": MAX_OUTPUT_TOKENS, "temperature": 0.2},
        )
    if response.get("stopReason") != "end_turn":
        raise IncompleteResponse("Bedrock did not finish with a complete answer")
    text = "".join(block.get("text", "") for block in response["output"]["message"]["content"])
    usage = response.get("usage", {})
    metadata = {
        "provider": "bedrock", "model": settings.aws_bedrock_model_id,
        "usage": {"input_tokens": usage.get("inputTokens", 0), "output_tokens": usage.get("outputTokens", 0),
                  "total_tokens": usage.get("totalTokens", 0)},
    }
    return _parse_output(text, metadata, snap), metadata


async def _run_agent(provider: str, snap: dict, feedback: str | None) -> tuple[Interpretation, dict]:
    call = _run_akamai(snap, feedback) if provider == "akamai" else asyncio.to_thread(_bedrock_request, snap, feedback)
    return await asyncio.wait_for(call, TIMEOUT_S)


def model_enabled() -> bool:
    """True when an AI brief can be requested (provider on and its credentials present)."""
    if settings.model_provider == "akamai":
        return bool(settings.akamai_api_key) or bool(settings.aws_fallback_enabled and settings.aws_bedrock_model_id)
    return False


async def interpret(snap: dict, use_model: bool = True) -> tuple[dict, str]:
    """Validated brief plus audited provider ID. Failures preserve the rules and manager control."""
    base = fallback.build(snap, snap.get("analogs"))
    if not use_model or settings.model_provider == "none":
        return base.model_dump(mode="json"), FALLBACK_ID
    providers = ["akamai"] if settings.model_provider == "akamai" else []
    if providers and settings.aws_fallback_enabled and settings.aws_bedrock_model_id:
        providers.append("bedrock")
    allowed = allowed_numbers(snap)
    failures: list[dict] = []
    requests: list[dict] = []
    attempts = 0
    for provider in providers:
        if provider == "akamai" and not settings.akamai_api_key:
            failures.append({"provider": provider, "problems": ["AKAMAI_API_KEY not configured"]})
            continue
        feedback = None
        # Two Akamai attempts (initial + validation repair), at most one Bedrock call.
        for _ in range(2 if provider == "akamai" else 1):
            attempts += 1
            try:
                out, metadata = await _run_agent(provider, snap, feedback)
                requests.append(metadata)
            except InvalidModelOutput as e:
                requests.append(e.metadata)
                problems = e.problems
            except (ValidationError, IncompleteResponse) as e:
                problems = [f"invalid structured response: {type(e).__name__}"]
            except Exception as e:  # network/auth/timeouts use fallback, never expose credential-bearing exceptions
                log.warning("%s interpretation failed (%s)", provider, type(e).__name__)
                failures.append({"provider": provider, "problems": [f"model call failed: {type(e).__name__}"]})
                break
            else:
                problems = validate(out, snap, allowed)
                if not problems:
                    # Deterministic counterfactuals and safety watch items are authoritative.
                    out.what_would_change = base.what_would_change
                    out.watch_next_6h = list(dict.fromkeys([*base.watch_next_6h, *out.watch_next_6h]))
                    out.alert_summaries = {**base.alert_summaries, **out.alert_summaries}
                    out.summary = _concise_summary(out.summary or base.summary)
                    out.uncertainty = out.uncertainty or base.uncertainty
                    out.evidence_rule_ids = out.evidence_rule_ids or base.evidence_rule_ids
                    d: dict[str, Any] = out.model_dump(mode="json")
                    d["validation"] = {"ok": True, "attempts": attempts, "problems": [], "context_views": list(VIEWS)}
                    d["inference"] = {"provider": provider, "fallback_used": provider != "akamai",
                                      "requests": requests, "failures": failures}
                    mid = settings.akamai_model_id if provider == "akamai" else settings.aws_bedrock_model_id
                    return d, f"{provider}:{mid}"
            failures.append({"provider": provider, "problems": problems})
            feedback = "; ".join(problems)
    d = base.model_dump(mode="json")
    d["validation"] = {"ok": False, "attempts": attempts,
                       "problems": [p for f in failures for p in f["problems"]] or ["Unsupported MODEL_PROVIDER; use akamai or none"]}
    d["inference"] = {"provider": "template", "fallback_used": True, "requests": requests, "failures": failures}
    return d, FALLBACK_ID


async def hazard_sentence(system: str, user: str) -> tuple[str | None, str]:
    """One short sentence from Akamai (used for notification wording).

    Returns (None, "none") when inference is off or no key is configured, so callers use their template.
    """
    if settings.model_provider != "akamai" or not settings.akamai_api_key:
        return None, "none"
    from openai import AsyncOpenAI

    schema = {"type": "object", "properties": {"explanation": {"type": "string", "maxLength": 350}},
              "required": ["explanation"], "additionalProperties": False}
    async with AsyncOpenAI(api_key=settings.akamai_api_key, base_url=settings.akamai_base_url,
                           timeout=30, max_retries=0) as client:
        response = await client.chat.completions.create(
            model=settings.akamai_model_id,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema", "json_schema": {"name": "weather_draft", "schema": schema}},
            temperature=0.2, max_tokens=200,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise ValueError("empty model response")
    return json.loads(content)["explanation"], f"akamai:{settings.akamai_model_id}"
