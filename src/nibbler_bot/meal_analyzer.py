from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from openai import AsyncOpenAI, NOT_GIVEN

from .config import Settings
from .models import MealAnalysis, MealItem, OpenAIUsage


SYSTEM_PROMPT = """
You estimate calories from one food or drink photo for a Telegram bot.

Rules:
- Be practical and concise.
- Use the photo plus the user's text. If the user provides corrections, trust them over the image.
- Include off-photo items only if the user explicitly mentions them.
- Prefer packaged-product calorie estimates when the product is clearly recognizable.
- For restaurant or home-cooked meals, make realistic portion estimates and mention uncertainty in notes.
- Return integer calories.
- Keep item names short and human-readable.
- If the image is unclear, still provide your best estimate and mention the uncertainty.
- If there is no edible item at all, return an empty items list, total_calories 0, and explain that in notes.
""".strip()


RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "amount": {"type": "string"},
                    "calories": {"type": "integer"},
                },
                "required": ["name", "amount", "calories"],
            },
        },
        "total_calories": {"type": "integer"},
        "notes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
    },
    "required": ["items", "total_calories", "notes", "confidence"],
}


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    analysis: MealAnalysis
    usage: OpenAIUsage
    raw_json: dict[str, object]


class MealAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=float(settings.openai_request_timeout_seconds),
        )

    async def analyze(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        caption_text: str,
        correction_text: str,
    ) -> AnalysisResult:
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        prompt = self._build_user_prompt(caption_text=caption_text, correction_text=correction_text)
        response = await self._client.responses.create(
            model=self._settings.openai_model,
            instructions=SYSTEM_PROMPT,
            reasoning=(
                {"effort": self._settings.openai_reasoning_effort}
                if self._settings.openai_reasoning_effort
                else NOT_GIVEN
            ),
            max_output_tokens=self._settings.openai_max_output_tokens,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "detail": "high",
                            "image_url": f"data:{mime_type};base64,{image_b64}",
                        },
                    ],
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "meal_analysis",
                    "schema": RESPONSE_SCHEMA,
                    "strict": True,
                }
            },
        )
        payload = json.loads(response.output_text)
        analysis = MealAnalysis(
            items=[
                MealItem(
                    name=str(item.get("name", "")).strip(),
                    amount=str(item.get("amount", "")).strip(),
                    calories=int(item.get("calories", 0)),
                )
                for item in payload.get("items", [])
                if isinstance(item, dict)
            ],
            total_calories=int(payload.get("total_calories", 0)),
            notes=[str(note).strip() for note in payload.get("notes", []) if str(note).strip()],
            confidence=str(payload.get("confidence", "medium") or "medium"),
        )
        usage = self._extract_usage(response)
        return AnalysisResult(analysis=analysis, usage=usage, raw_json=payload)

    def _build_user_prompt(self, *, caption_text: str, correction_text: str) -> str:
        normalized_caption = caption_text.strip() or "No caption provided."
        normalized_correction = correction_text.strip() or "No follow-up correction provided."
        return (
            "Estimate calories for exactly what the user consumed.\n"
            f"Original user note: {normalized_caption}\n"
            f"Follow-up correction: {normalized_correction}\n"
            "Return a clean breakdown plus a total."
        )

    def _extract_usage(self, response: object) -> OpenAIUsage:
        usage_payload: dict[str, object]
        if hasattr(response, "model_dump"):
            usage_payload = response.model_dump().get("usage", {})  # type: ignore[assignment]
        else:
            usage = getattr(response, "usage", None)
            if usage is None:
                usage_payload = {}
            elif hasattr(usage, "model_dump"):
                usage_payload = usage.model_dump()
            else:
                usage_payload = dict(getattr(usage, "__dict__", {}))
        input_tokens = int(usage_payload.get("input_tokens", 0) or 0)
        output_tokens = int(usage_payload.get("output_tokens", 0) or 0)
        details = usage_payload.get("input_tokens_details", {})
        cached_input_tokens = 0
        if isinstance(details, dict):
            cached_input_tokens = int(details.get("cached_tokens", 0) or 0)
        total_cost_usd = self._settings.pricing.estimate_cost_usd(
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
        )
        return OpenAIUsage(
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            total_cost_usd=total_cost_usd,
        )
