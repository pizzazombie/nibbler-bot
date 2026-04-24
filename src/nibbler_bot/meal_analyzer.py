from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from importlib import resources

from openai import AsyncOpenAI, NOT_GIVEN

from .config import Settings
from .models import MealAnalysis, MealItem, OpenAIUsage


LOGGER = logging.getLogger(__name__)


class MealAnalysisError(Exception):
    pass


class MealAnalysisUserMessageError(MealAnalysisError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def load_system_prompt() -> str:
    return (
        resources.files("nibbler_bot")
        .joinpath("prompts", "meal_analysis_system_prompt.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


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
                    "count_estimate": {"type": ["number", "null"]},
                    "unit_label": {"type": ["string", "null"]},
                    "estimated_weight_g": {"type": ["number", "null"]},
                    "estimated_volume_ml": {"type": ["number", "null"]},
                    "calories": {"type": "integer"},
                    "protein_g": {"type": "number"},
                    "fat_g": {"type": "number"},
                    "carbs_g": {"type": "number"},
                    "fiber_g": {"type": "number"},
                    "estimation_basis": {
                        "type": "string",
                        "enum": [
                            "counted",
                            "package_label",
                            "user_text",
                            "portion_reference",
                            "plate_fraction",
                            "visual_estimate",
                            "mixed_dish_estimate",
                        ],
                    },
                    "item_confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "reasoning_note_short": {"type": ["string", "null"]},
                },
                "required": [
                    "name",
                    "amount",
                    "count_estimate",
                    "unit_label",
                    "estimated_weight_g",
                    "estimated_volume_ml",
                    "calories",
                    "protein_g",
                    "fat_g",
                    "carbs_g",
                    "fiber_g",
                    "estimation_basis",
                    "item_confidence",
                    "reasoning_note_short",
                ],
            },
        },
        "total_calories": {"type": "integer"},
        "total_protein_g": {"type": "number"},
        "total_fat_g": {"type": "number"},
        "total_carbs_g": {"type": "number"},
        "total_fiber_g": {"type": "number"},
        "notes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "follow_up_question": {"type": "string"},
    },
    "required": [
        "items",
        "total_calories",
        "total_protein_g",
        "total_fat_g",
        "total_carbs_g",
        "total_fiber_g",
        "notes",
        "confidence",
        "follow_up_question",
    ],
}


@dataclass(frozen=True, slots=True)
class AnalysisRequestRecord:
    request_kind: str
    model: str
    usage: OpenAIUsage


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    analysis: MealAnalysis
    usage: OpenAIUsage
    raw_json: dict[str, object]
    requests: list[AnalysisRequestRecord]


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
        image_bytes: bytes | None,
        mime_type: str | None,
        caption_text: str,
        correction_text: str,
    ) -> AnalysisResult:
        request_records: list[AnalysisRequestRecord] = []
        analysis_response = await self._run_structured_request(
            model=self._settings.openai_model,
            reasoning_effort=self._settings.openai_reasoning_effort,
            instructions=load_system_prompt(),
            prompt=self._build_primary_user_prompt(
                caption_text=caption_text,
                correction_text=correction_text,
            ),
            schema_name="meal_analysis",
            schema=RESPONSE_SCHEMA,
            image_bytes=image_bytes,
            mime_type=mime_type,
            max_output_tokens=max(self._settings.openai_max_output_tokens, 1800),
        )
        analysis_usage = self._extract_usage(analysis_response)
        request_records.append(
            AnalysisRequestRecord(
                request_kind="meal_analysis",
                model=self._settings.openai_model,
                usage=analysis_usage,
            )
        )
        payload = self._extract_structured_payload(analysis_response)
        analysis = self._parse_analysis_payload(payload)

        total_usage = OpenAIUsage(
            input_tokens=sum(record.usage.input_tokens for record in request_records),
            cached_input_tokens=sum(record.usage.cached_input_tokens for record in request_records),
            output_tokens=sum(record.usage.output_tokens for record in request_records),
            total_cost_usd=round(
                sum(record.usage.total_cost_usd for record in request_records),
                6,
            ),
        )
        return AnalysisResult(
            analysis=analysis,
            usage=total_usage,
            raw_json=payload,
            requests=request_records,
        )

    async def _run_structured_request(
        self,
        *,
        model: str,
        reasoning_effort: str | None,
        instructions: str,
        prompt: str,
        schema_name: str,
        schema: dict[str, object],
        image_bytes: bytes | None,
        mime_type: str | None,
        max_output_tokens: int,
    ):
        content: list[dict[str, object]] = [{"type": "input_text", "text": prompt}]
        if image_bytes is not None and mime_type is not None:
            image_b64 = base64.b64encode(image_bytes).decode("ascii")
            content.append(
                {
                    "type": "input_image",
                    "detail": "auto",
                    "image_url": f"data:{mime_type};base64,{image_b64}",
                }
            )
        return await self._client.responses.create(
            model=model,
            instructions=instructions,
            reasoning={"effort": reasoning_effort} if reasoning_effort else NOT_GIVEN,
            max_output_tokens=max_output_tokens,
            input=[
                {
                    "role": "user",
                    "content": content,
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
        )

    def _build_primary_user_prompt(
        self,
        *,
        caption_text: str,
        correction_text: str,
    ) -> str:
        normalized_caption = caption_text.strip() or "No caption provided."
        normalized_correction = correction_text.strip() or "No follow-up correction provided."
        return (
            "Estimate calories and macros for exactly what the user consumed.\n"
            "The user may provide a photo, a text-only meal description, or both.\n"
            f"Original user note: {normalized_caption}\n"
            f"Follow-up correction: {normalized_correction}\n"
            "Do one complete pass: identify edible components, estimate portion size, then calculate calories and macros.\n"
            "When countable foods are present, count visible units before converting to grams.\n"
            "If the image is ambiguous, still provide your best estimate and use the confidence fields honestly.\n"
            "If your estimate would benefit from clarification, ask one short concrete follow-up question in follow_up_question instead of leaving uncertainty vague.\n"
            "Return a clean breakdown plus totals for calories, protein, fat, carbs, and fiber."
        )

    def _extract_structured_payload(self, response: object) -> dict[str, object]:
        output_text = str(getattr(response, "output_text", "") or "").strip()
        if output_text:
            try:
                return json.loads(self._strip_code_fences(output_text))
            except json.JSONDecodeError:
                LOGGER.warning("Could not parse response.output_text as JSON.")

        payload = response.model_dump() if hasattr(response, "model_dump") else {}
        if not isinstance(payload, dict):
            payload = {}

        error_payload = payload.get("error")
        if error_payload:
            raise MealAnalysisUserMessageError(
                "The model request failed before it could return a meal estimate. Please try again in a moment."
            )

        incomplete_details = payload.get("incomplete_details")
        if incomplete_details:
            raise MealAnalysisUserMessageError(
                "The estimate was cut off before it finished. Please try again, or send a short text description with the photo."
            )

        for output in payload.get("output", []):
            if not isinstance(output, dict) or output.get("type") != "message":
                continue
            for item in output.get("content", []):
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "refusal":
                    refusal_text = str(item.get("refusal", "") or "").strip()
                    if refusal_text:
                        raise MealAnalysisUserMessageError(refusal_text)
                    raise MealAnalysisUserMessageError(
                        "The model refused to produce a structured estimate for this input. Please add a short text description of the meal and try again."
                    )
                candidate_text = str(item.get("text", "") or "").strip()
                if candidate_text:
                    try:
                        return json.loads(self._strip_code_fences(candidate_text))
                    except json.JSONDecodeError:
                        LOGGER.warning("Could not parse response content text as JSON.")

        LOGGER.warning("Structured payload missing or unparsable. Response keys: %s", sorted(payload.keys()))
        raise MealAnalysisUserMessageError(
            "I couldn't turn that response into a meal estimate. Please try again, or send a short text description like '2 eggs, toast, and coffee'."
        )

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        normalized = text.strip()
        if normalized.startswith("```") and normalized.endswith("```"):
            lines = normalized.splitlines()
            if len(lines) >= 3:
                return "\n".join(lines[1:-1]).strip()
        return normalized

    def _optional_str(self, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _parse_analysis_payload(self, payload: dict[str, object]) -> MealAnalysis:
        return MealAnalysis(
            items=[
                MealItem(
                    name=str(item.get("name", "")).strip(),
                    amount=str(item.get("amount", "")).strip(),
                    calories=int(item.get("calories", 0)),
                    count_estimate=(
                        round(float(item.get("count_estimate", 0) or 0), 1)
                        if item.get("count_estimate") is not None
                        else None
                    ),
                    unit_label=self._optional_str(item.get("unit_label")),
                    estimated_weight_g=(
                        round(float(item.get("estimated_weight_g", 0) or 0), 1)
                        if item.get("estimated_weight_g") is not None
                        else None
                    ),
                    estimated_volume_ml=(
                        round(float(item.get("estimated_volume_ml", 0) or 0), 1)
                        if item.get("estimated_volume_ml") is not None
                        else None
                    ),
                    protein_g=round(float(item.get("protein_g", 0) or 0), 1),
                    fat_g=round(float(item.get("fat_g", 0) or 0), 1),
                    carbs_g=round(float(item.get("carbs_g", 0) or 0), 1),
                    fiber_g=round(float(item.get("fiber_g", 0) or 0), 1),
                    estimation_basis=self._optional_str(item.get("estimation_basis")),
                    item_confidence=str(item.get("item_confidence", "medium") or "medium"),
                    reasoning_note_short=self._optional_str(item.get("reasoning_note_short")),
                )
                for item in payload.get("items", [])
                if isinstance(item, dict)
            ],
            total_calories=int(payload.get("total_calories", 0)),
            total_protein_g=round(float(payload.get("total_protein_g", 0) or 0), 1),
            total_fat_g=round(float(payload.get("total_fat_g", 0) or 0), 1),
            total_carbs_g=round(float(payload.get("total_carbs_g", 0) or 0), 1),
            total_fiber_g=round(float(payload.get("total_fiber_g", 0) or 0), 1),
            notes=[str(note).strip() for note in payload.get("notes", []) if str(note).strip()],
            confidence=str(payload.get("confidence", "medium") or "medium"),
            follow_up_question=str(payload.get("follow_up_question", "") or "").strip(),
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
