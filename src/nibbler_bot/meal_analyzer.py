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


def load_system_prompt() -> str:
    return (
        resources.files("nibbler_bot")
        .joinpath("prompts", "meal_analysis_system_prompt.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def load_scan_prompt() -> str:
    return (
        resources.files("nibbler_bot")
        .joinpath("prompts", "meal_scan_system_prompt.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


SCAN_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "components": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "countable": {"type": "boolean"},
                    "visible_count_estimate": {"type": ["number", "null"]},
                    "portion_cue": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                },
                "required": [
                    "name",
                    "countable",
                    "visible_count_estimate",
                    "portion_cue",
                    "confidence",
                ],
            },
        },
        "scene_tags": {
            "type": "array",
            "items": {"type": "string"},
        },
        "complexity": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "needs_precise_counting": {"type": "boolean"},
        "small_objects_detected": {"type": "boolean"},
        "mixed_plate": {"type": "boolean"},
        "follow_up_candidate": {"type": "string"},
        "notes": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "components",
        "scene_tags",
        "complexity",
        "needs_precise_counting",
        "small_objects_detected",
        "mixed_plate",
        "follow_up_candidate",
        "notes",
    ],
}


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
class ScanComponent:
    name: str
    countable: bool
    visible_count_estimate: float | None
    portion_cue: str
    confidence: str


@dataclass(frozen=True, slots=True)
class ScanResult:
    components: list[ScanComponent]
    scene_tags: list[str]
    complexity: str
    needs_precise_counting: bool
    small_objects_detected: bool
    mixed_plate: bool
    follow_up_candidate: str
    notes: list[str]


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
        scan_response = await self._run_structured_request(
            model=self._settings.openai_model,
            reasoning_effort=self._settings.openai_reasoning_effort,
            instructions=load_scan_prompt(),
            prompt=self._build_scan_user_prompt(
                caption_text=caption_text,
                correction_text=correction_text,
            ),
            schema_name="meal_scan",
            schema=SCAN_SCHEMA,
            image_bytes=image_bytes,
            mime_type=mime_type,
            max_output_tokens=max(self._settings.openai_max_output_tokens, 700),
        )
        scan_usage = self._extract_usage(scan_response)
        request_records.append(
            AnalysisRequestRecord(
                request_kind="meal_scan",
                model=self._settings.openai_model,
                usage=scan_usage,
            )
        )
        scan_result = self._parse_scan_result(json.loads(scan_response.output_text))

        analysis_response = await self._run_structured_request(
            model=self._settings.openai_model,
            reasoning_effort=self._settings.openai_reasoning_effort,
            instructions=load_system_prompt(),
            prompt=self._build_final_user_prompt(
                caption_text=caption_text,
                correction_text=correction_text,
                scan_result=scan_result,
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
        payload = await self._parse_or_retry_response_json(
            response=analysis_response,
            request_kind="meal_analysis_retry",
            model=self._settings.openai_model,
            reasoning_effort=self._settings.openai_reasoning_effort,
            instructions=load_system_prompt(),
            prompt=self._build_final_user_prompt(
                caption_text=caption_text,
                correction_text=correction_text,
                scan_result=scan_result,
            ),
            schema_name="meal_analysis",
            schema=RESPONSE_SCHEMA,
            image_bytes=image_bytes,
            mime_type=mime_type,
            retry_max_output_tokens=max(self._settings.openai_max_output_tokens, 2600),
            request_records=request_records,
        )
        analysis = self._parse_analysis_payload(payload)

        if self._should_escalate(scan_result, analysis):
            escalation_model = self._settings.openai_complex_meal_model
            escalation_effort = self._settings.openai_complex_reasoning_effort
            if escalation_model != self._settings.openai_model or (
                escalation_effort != self._settings.openai_reasoning_effort
            ):
                escalated_response = await self._run_structured_request(
                    model=escalation_model,
                    reasoning_effort=escalation_effort,
                    instructions=load_system_prompt(),
                    prompt=self._build_final_user_prompt(
                        caption_text=caption_text,
                        correction_text=correction_text,
                        scan_result=scan_result,
                    ),
                    schema_name="meal_analysis",
                    schema=RESPONSE_SCHEMA,
                    image_bytes=image_bytes,
                    mime_type=mime_type,
                    max_output_tokens=max(self._settings.openai_max_output_tokens, 2200),
                )
                escalation_usage = self._extract_usage(escalated_response)
                request_records.append(
                    AnalysisRequestRecord(
                        request_kind="meal_analysis_escalated",
                        model=escalation_model,
                        usage=escalation_usage,
                    )
                )
                payload = await self._parse_or_retry_response_json(
                    response=escalated_response,
                    request_kind="meal_analysis_escalated_retry",
                    model=escalation_model,
                    reasoning_effort=escalation_effort,
                    instructions=load_system_prompt(),
                    prompt=self._build_final_user_prompt(
                        caption_text=caption_text,
                        correction_text=correction_text,
                        scan_result=scan_result,
                    ),
                    schema_name="meal_analysis",
                    schema=RESPONSE_SCHEMA,
                    image_bytes=image_bytes,
                    mime_type=mime_type,
                    retry_max_output_tokens=max(self._settings.openai_max_output_tokens, 3200),
                    request_records=request_records,
                )
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
                    "detail": "high",
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

    async def _parse_or_retry_response_json(
        self,
        *,
        response: object,
        request_kind: str,
        model: str,
        reasoning_effort: str | None,
        instructions: str,
        prompt: str,
        schema_name: str,
        schema: dict[str, object],
        image_bytes: bytes | None,
        mime_type: str | None,
        retry_max_output_tokens: int,
        request_records: list[AnalysisRequestRecord],
    ) -> dict[str, object]:
        output_text = str(getattr(response, "output_text", "") or "").strip()
        if output_text:
            try:
                return json.loads(output_text)
            except json.JSONDecodeError:
                LOGGER.warning("Structured output JSON was incomplete for %s; retrying.", request_kind)
        else:
            LOGGER.warning("Structured output text was empty for %s; retrying.", request_kind)

        retry_response = await self._run_structured_request(
            model=model,
            reasoning_effort=reasoning_effort,
            instructions=instructions,
            prompt=prompt,
            schema_name=schema_name,
            schema=schema,
            image_bytes=image_bytes,
            mime_type=mime_type,
            max_output_tokens=retry_max_output_tokens,
        )
        retry_usage = self._extract_usage(retry_response)
        request_records.append(
            AnalysisRequestRecord(
                request_kind=request_kind,
                model=model,
                usage=retry_usage,
            )
        )
        retry_output_text = str(getattr(retry_response, "output_text", "") or "").strip()
        return json.loads(retry_output_text)

    def _build_scan_user_prompt(self, *, caption_text: str, correction_text: str) -> str:
        normalized_caption = caption_text.strip() or "No caption provided."
        normalized_correction = correction_text.strip() or "No follow-up correction provided."
        return (
            "Inspect the meal and identify components before estimating nutrition.\n"
            "Focus on what items are present, what needs counting, and what looks hard to size correctly.\n"
            f"Original user note: {normalized_caption}\n"
            f"Follow-up correction: {normalized_correction}\n"
            "Return only the structured scan result."
        )

    def _build_final_user_prompt(
        self,
        *,
        caption_text: str,
        correction_text: str,
        scan_result: ScanResult,
    ) -> str:
        normalized_caption = caption_text.strip() or "No caption provided."
        normalized_correction = correction_text.strip() or "No follow-up correction provided."
        component_lines = []
        for component in scan_result.components:
            count_text = (
                f"~{component.visible_count_estimate:g} visible"
                if component.visible_count_estimate is not None
                else "count not clear"
            )
            component_lines.append(
                f"- {component.name} | countable={str(component.countable).lower()} | "
                f"{count_text} | cue={component.portion_cue or 'none'} | confidence={component.confidence}"
            )
        component_summary = "\n".join(component_lines) if component_lines else "- no clear components detected"
        scene_tags = ", ".join(scan_result.scene_tags) if scan_result.scene_tags else "none"
        notes = "; ".join(scan_result.notes) if scan_result.notes else "none"
        follow_up_candidate = scan_result.follow_up_candidate or "none"
        return (
            "Estimate calories and macros for exactly what the user consumed.\n"
            "The user may provide a photo, a text-only meal description, or both.\n"
            f"Original user note: {normalized_caption}\n"
            f"Follow-up correction: {normalized_correction}\n"
            "Use this earlier meal scan as guidance, but correct it if your final inspection supports a better answer.\n"
            f"Scan components:\n{component_summary}\n"
            f"Scene tags: {scene_tags}\n"
            f"Complexity: {scan_result.complexity}\n"
            f"Needs precise counting: {str(scan_result.needs_precise_counting).lower()}\n"
            f"Small objects detected: {str(scan_result.small_objects_detected).lower()}\n"
            f"Mixed plate: {str(scan_result.mixed_plate).lower()}\n"
            f"Scan notes: {notes}\n"
            f"Best clarification candidate if still needed: {follow_up_candidate}\n"
            "Return a clean breakdown plus totals for calories, protein, fat, carbs, and fiber."
        )

    def _parse_scan_result(self, payload: dict[str, object]) -> ScanResult:
        return ScanResult(
            components=[
                ScanComponent(
                    name=str(component.get("name", "")).strip(),
                    countable=bool(component.get("countable", False)),
                    visible_count_estimate=(
                        round(float(component.get("visible_count_estimate", 0) or 0), 1)
                        if component.get("visible_count_estimate") is not None
                        else None
                    ),
                    portion_cue=str(component.get("portion_cue", "")).strip(),
                    confidence=str(component.get("confidence", "medium") or "medium"),
                )
                for component in payload.get("components", [])
                if isinstance(component, dict)
            ],
            scene_tags=[str(tag).strip() for tag in payload.get("scene_tags", []) if str(tag).strip()],
            complexity=str(payload.get("complexity", "medium") or "medium"),
            needs_precise_counting=bool(payload.get("needs_precise_counting", False)),
            small_objects_detected=bool(payload.get("small_objects_detected", False)),
            mixed_plate=bool(payload.get("mixed_plate", False)),
            follow_up_candidate=str(payload.get("follow_up_candidate", "") or "").strip(),
            notes=[str(note).strip() for note in payload.get("notes", []) if str(note).strip()],
        )

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

    def _should_escalate(self, scan_result: ScanResult, analysis: MealAnalysis) -> bool:
        if scan_result.needs_precise_counting or scan_result.small_objects_detected:
            return True
        if scan_result.mixed_plate and len(scan_result.components) >= 3:
            return True
        if scan_result.complexity == "high":
            return True
        if len(scan_result.components) >= 5:
            return True
        if analysis.confidence == "low":
            return True
        if analysis.follow_up_question:
            return True
        return any(item.item_confidence == "low" for item in analysis.items)

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
