from __future__ import annotations

import json

from pydantic import BaseModel, Field

from backend.app.llm.client import LLMClient
from backend.app.llm.grounding import verify_grounding
from backend.app.models import LLMCall, Recommendation
from backend.app.notify.messages import check_message


class ExtractedAlert(BaseModel):
    ice_min_in: float | None = None
    ice_max_in: float | None = None
    wind_gust_mph: float | None = None
    hail_in: float | None = None
    timing_phrases: list[str] = Field(default_factory=list)
    safety_actions: list[str] = Field(default_factory=list)


class DraftedMessage(BaseModel):
    sms: str
    email_subject: str
    email_body: str


class DraftingService:
    def __init__(self, client: LLMClient) -> None:
        self.client = client

    async def extract_alert(self, text: str) -> tuple[ExtractedAlert, LLMCall]:
        prompt = (
            "Extract only explicit weather quantities and instructions into JSON. Use null for absent "
            "numbers. This extraction is corroborating evidence and must not infer a closure.\n\n"
            + text
        )
        try:
            output = await self.client.complete(
                [
                    {
                        "role": "system",
                        "content": "You extract facts; you never make operating decisions.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            parsed = ExtractedAlert.model_validate_json(output)
            return parsed, LLMCall(
                model=self.client.model,
                parameters={"temperature": 0.1, "response_format": "json"},
                prompt=prompt,
                output=output,
                grounding_check=True,
            )
        except Exception as exc:
            fallback = ExtractedAlert()
            return fallback, LLMCall(
                model=self.client.model,
                parameters={},
                prompt=prompt,
                output=f"Template fallback: {exc}",
                grounding_check=True,
                used_fallback=True,
            )

    async def rationale(self, recommendation: Recommendation) -> tuple[str, LLMCall]:
        source = recommendation.model_dump(mode="json")
        prompt = (
            "Draft one concise, plain-language recommendation rationale. Every number, time, place, "
            "and threshold must appear exactly in the JSON. State that a human decides. JSON:\n"
            + json.dumps(source, sort_keys=True)
        )
        last_output = ""
        for attempt in range(2):
            try:
                last_output = await self.client.complete(
                    [
                        {
                            "role": "system",
                            "content": "Use only supplied facts. Never select or change the posture.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                )
                grounded, errors = verify_grounding(last_output, source)
                if grounded:
                    return last_output, LLMCall(
                        model=self.client.model,
                        parameters={"temperature": 0.0, "attempt": attempt + 1},
                        prompt=prompt,
                        output=last_output,
                        grounding_check=True,
                    )
                prompt += "\nThe prior draft failed grounding: " + "; ".join(errors)
            except Exception as exc:
                last_output = str(exc)
                break
        fallback = recommendation.rationale_template
        return fallback, LLMCall(
            model=self.client.model,
            parameters={"attempts": 2},
            prompt=prompt,
            output=last_output or fallback,
            grounding_check=False,
            used_fallback=True,
        )

    async def message_variant(
        self,
        recommendation: Recommendation,
        template_sms: str,
        template_subject: str,
        template_body: str,
        variant: str,
    ) -> tuple[DraftedMessage, LLMCall]:
        fallback = DraftedMessage(
            sms=template_sms,
            email_subject=template_subject,
            email_body=template_body,
        )
        sources = {
            "recommendation": recommendation.model_dump(mode="json"),
            "approved_template": fallback.model_dump(),
            "variant": variant,
        }
        prompt = (
            "Rewrite the approved template for the named audience variant as JSON with sms, "
            "email_subject, and email_body. SMS must be 320 characters or less. Preserve the five "
            "elements: what is happening, applies to you, what to do, by when/until when, and who "
            "to contact. Use only facts and numbers in this source JSON:\n"
            + json.dumps(sources, sort_keys=True)
        )
        try:
            output = await self.client.complete(
                [
                    {
                        "role": "system",
                        "content": "Draft employee notices only. Never select or change posture.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            drafted = DraftedMessage.model_validate_json(output)
            grounded, grounding_errors = verify_grounding(output, sources)
            message_errors = check_message(drafted.sms, drafted.email_body)
            if not grounded or message_errors:
                raise ValueError("; ".join(grounding_errors + message_errors))
            return drafted, LLMCall(
                model=self.client.model,
                parameters={"temperature": 0.0, "response_format": "json"},
                prompt=prompt,
                output=output,
                grounding_check=True,
            )
        except Exception as exc:
            return fallback, LLMCall(
                model=self.client.model,
                parameters={},
                prompt=prompt,
                output=f"Template fallback: {exc}",
                grounding_check=True,
                used_fallback=True,
            )
