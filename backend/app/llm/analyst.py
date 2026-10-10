from __future__ import annotations

import json

from backend.app.llm.client import LLMClient
from backend.app.llm.grounding import verify_grounding
from backend.app.models import AnalystResponse, Employee, EvidenceBundle, LLMCall, Recommendation


def answer_question(
    question: str,
    recommendation: Recommendation,
    evidence: EvidenceBundle,
    employees: list[Employee],
) -> AnalystResponse:
    """Read-only fallback analyst. Tool calls are exposed and no record-writing tool exists."""
    lowered = question.lower()
    citations = [item.id for item in recommendation.inputs]
    if "who" in lowered or "affected" in lowered:
        tool_calls = [
            {"tool": "resolve_recipients", "arguments": {"facility_id": recommendation.facility_id}}
        ]
        on_site = sum(employee.status_today.value == "on_site" for employee in employees)
        answer = (
            f"The roster has {len(employees)} assigned employees and {on_site} currently marked on site. "
            "The notification preview applies the detail, leave, telework, essential-personnel, and "
            "accessibility rules to every person and records a reason for each inclusion or exclusion."
        )
    elif "why not" in lowered or "closure" in lowered:
        tool_calls = [
            {"tool": "evaluate", "arguments": {"as_of": recommendation.as_of.isoformat()}},
            {"tool": "counterfactual", "arguments": {"target": "CLOSED"}},
        ]
        change = next(
            (item for item in recommendation.what_would_change if item.then.value == "CLOSED"), None
        )
        answer = f"The engine recommends {recommendation.posture.value}, not closure, under its timing table. "
        answer += (
            change.condition.capitalize() + " would change it to CLOSED."
            if change
            else "No smaller tested perturbation changed it to CLOSED."
        )
    elif "what if" in lowered:
        tool_calls = [{"tool": "counterfactual", "arguments": {"question": question}}]
        answer = "The precomputed boundary cases are: " + "; ".join(
            f"if {item.condition}, then {item.then.value}"
            for item in recommendation.what_would_change
        )
    else:
        tool_calls = [
            {"tool": "get_evidence", "arguments": {"facility_id": recommendation.facility_id}}
        ]
        answer = recommendation.rationale_template
    if evidence.mode != "live":
        answer += f" Evidence mode is {evidence.mode}, so confidence is reduced."
    return AnalystResponse(
        answer=answer, citations=citations, tool_calls=tool_calls, used_fallback=True
    )


async def answer_with_inference(
    question: str,
    recommendation: Recommendation,
    evidence: EvidenceBundle,
    employees: list[Employee],
    client: LLMClient,
) -> tuple[AnalystResponse, LLMCall]:
    tool_result = answer_question(question, recommendation, evidence, employees)
    context = {
        "question": question,
        "tool_calls": tool_result.tool_calls,
        "tool_result": tool_result.answer,
        "recommendation": recommendation.model_dump(mode="json"),
        "evidence_ids": tool_result.citations,
    }
    prompt = (
        "Answer the question from the read-only tool result and JSON only. Cite evidence ids. "
        "Do not select a new posture and do not imply you can approve, send, or write records.\n"
        + json.dumps(context, sort_keys=True)
    )
    try:
        output = await client.complete(
            [
                {
                    "role": "system",
                    "content": "You are a read-only analyst over deterministic decision tools.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        grounded, errors = verify_grounding(output, context)
        if not grounded:
            raise ValueError("; ".join(errors))
        response = tool_result.model_copy(update={"answer": output, "used_fallback": False})
        return response, LLMCall(
            model=client.model,
            parameters={"temperature": 0.0},
            prompt=prompt,
            output=output,
            grounding_check=True,
        )
    except Exception as exc:
        return tool_result, LLMCall(
            model=client.model,
            parameters={},
            prompt=prompt,
            output=f"Deterministic analyst fallback: {exc}",
            grounding_check=True,
            used_fallback=True,
        )
