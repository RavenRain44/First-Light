"""Strands Agents interpretation layer.

One agent, five read-only tools over the current snapshot, strict Pydantic
output. The agent never decides: the posture and every number come from the
rules. Output is post-validated (every number in the rationale must exist in
the snapshot); on failure we retry once, then fall back to the deterministic
template. With no credentials configured the template is used directly.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from ai import fallback
from ai.prompts import SYSTEM_PROMPT, USER_PROMPT, Interpretation
from app.config import settings

log = logging.getLogger("closurecall.ai")
FALLBACK_ID = "deterministic-fallback"
TIMEOUT_S = 60
NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
# Durations/ordinals the brief itself uses ("next 6 hours", "24 h"); allowed even if not in the snapshot.
GENERIC_NUMBERS = {0.0, 1.0, 2.0, 3.0, 6.0, 12.0, 24.0, 36.0, 48.0, 100.0}


def default_model_id(provider: str) -> str:
    return {"anthropic": "claude-sonnet-5-5", "openai": "gpt-4o"}.get(provider, "")


def build_model():
    """Model from env: MODEL_PROVIDER = anthropic | bedrock | openai. Returns (model, model_id) or (None, reason)."""
    p = settings.model_provider
    mid = settings.model_id or default_model_id(p)
    if p == "anthropic":
        if not settings.anthropic_api_key:
            return None, "ANTHROPIC_API_KEY not set"
        from strands.models.anthropic import AnthropicModel
        return AnthropicModel(client_args={"api_key": settings.anthropic_api_key}, model_id=mid, max_tokens=2000,
                              params={"temperature": 0.2}), f"anthropic:{mid}"
    if p == "bedrock":
        if not mid:
            return None, "MODEL_ID required for bedrock"
        from strands.models.bedrock import BedrockModel
        return BedrockModel(model_id=mid, region_name=settings.aws_region, temperature=0.2, max_tokens=2000), f"bedrock:{mid}"
    if p == "openai":
        if not settings.openai_api_key:
            return None, "OPENAI_API_KEY not set"
        from strands.models.openai import OpenAIModel
        args = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            args["base_url"] = settings.openai_base_url
        return OpenAIModel(client_args=args, model_id=mid, params={"temperature": 0.2, "max_tokens": 2000}), f"openai:{mid}"
    return None, "MODEL_PROVIDER=none"


def allowed_numbers(snap: dict) -> set[float]:
    """Every number that appears in what the tools return or in the snapshot's inputs/rules."""
    from ai.tools import VIEWS

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
        tol = 0.5 * 10 ** -_decimals(s) + 1e-9  # "58" matches 58.3; "0.25" must match 0.25
        if not any(abs(v - a) <= tol for a in allowed) and not any(abs(-v - a) <= tol for a in allowed):
            bad.append(s)
    return bad


def validate(interp: Interpretation, snap: dict, allowed: set[float]) -> list[str]:
    problems = []
    bad = unsupported_numbers(interp.rationale_paragraph + " " + interp.headline, allowed)
    if bad:
        problems.append(f"numbers not found in snapshot: {', '.join(sorted(set(bad)))}")
    posture = snap["posture"]["posture"]
    words = posture.replace("_", " ").lower()
    if posture.lower() not in interp.rationale_paragraph.lower() and words not in interp.rationale_paragraph.lower() \
            and snap["posture"]["opm_label"].lower()[:20] not in interp.rationale_paragraph.lower():
        problems.append(f"rationale does not name the recommended posture {posture}")
    for other in ("CLOSED", "TELEWORK", "DELAYED_ARRIVAL", "EARLY_DISMISSAL", "NORMAL"):
        if other != posture and re.search(rf"\brecommend\w*\s+(an?\s+)?{other.replace('_', '[ _]')}", interp.rationale_paragraph, re.I):
            problems.append(f"rationale recommends {other}, not {posture}")
    return problems


async def _run_agent(model, snap: dict, feedback: str | None) -> tuple[Interpretation, list[str]]:
    from strands import Agent
    from ai.tools import build_tools

    calls: list[str] = []
    agent = Agent(model=model, system_prompt=SYSTEM_PROMPT, tools=build_tools(snap, calls), callback_handler=None)
    prompt = USER_PROMPT if not feedback else (
        f"{USER_PROMPT}\n\nYour previous answer was rejected: {feedback}. Use only numbers exactly as the tools return them.")
    result = await asyncio.wait_for(agent.invoke_async(prompt, structured_output_model=Interpretation), TIMEOUT_S)
    out = result.structured_output
    if not isinstance(out, Interpretation):
        out = Interpretation.model_validate(out)
    return out, calls


async def interpret(snap: dict, use_model: bool = True) -> tuple[dict, str]:
    """Return (interpretation dict, model id). Never raises."""
    base = fallback.build(snap, snap.get("analogs"))
    if not use_model:
        return base.model_dump(mode="json"), FALLBACK_ID
    model, model_id = build_model()
    if model is None:
        return base.model_dump(mode="json"), FALLBACK_ID
    allowed = allowed_numbers(snap)
    feedback, attempts, problems = None, 0, []
    for attempts in (1, 2):
        try:
            out, calls = await _run_agent(model, snap, feedback)
        except Exception as e:  # noqa: BLE001 - network, auth, schema; all fall back
            log.warning("interpretation agent failed: %s", e)
            problems = [f"model call failed: {type(e).__name__}"]
            break
        problems = validate(out, snap, allowed)
        if not problems:
            ids = {a["id"] for a in snap.get("alerts", [])}
            out.alert_summaries = {k: v for k, v in out.alert_summaries.items() if k in ids} or base.alert_summaries
            # The computed list is authoritative; the model may rephrase but not drop items.
            if len(out.what_would_change) < len(base.what_would_change):
                out.what_would_change = base.what_would_change
            d: dict[str, Any] = out.model_dump(mode="json")
            d["validation"] = {"ok": True, "attempts": attempts, "problems": [], "tools_called": calls}
            return d, model_id
        feedback = "; ".join(problems)
    d = base.model_dump(mode="json")
    d["validation"] = {"ok": False, "attempts": attempts, "problems": problems, "model_attempted": model_id}
    return d, FALLBACK_ID
