from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class MealItem:
    name: str
    amount: str
    calories: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class MealAnalysis:
    items: list[MealItem]
    total_calories: int
    notes: list[str] = field(default_factory=list)
    confidence: str = "medium"

    def to_dict(self) -> dict[str, object]:
        return {
            "items": [item.to_dict() for item in self.items],
            "total_calories": self.total_calories,
            "notes": list(self.notes),
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "MealAnalysis":
        raw_items = payload.get("items", [])
        items = [
            MealItem(
                name=str(item.get("name", "")),
                amount=str(item.get("amount", "")),
                calories=int(item.get("calories", 0)),
            )
            for item in raw_items
            if isinstance(item, dict)
        ]
        return cls(
            items=items,
            total_calories=int(payload.get("total_calories", 0)),
            notes=[str(item) for item in payload.get("notes", []) if str(item).strip()],
            confidence=str(payload.get("confidence", "medium") or "medium"),
        )

    @property
    def primary_item_name(self) -> str:
        if not self.items:
            return "Meal"
        return self.items[0].name


@dataclass(frozen=True, slots=True)
class UserProfile:
    chat_id: int
    username: str | None
    first_name: str | None
    display_name: str | None
    daily_calorie_limit: int | None
    is_authorized: bool
    password_attempts: int
    password_attempt_month: str | None
    onboarding_state: str | None
    state_payload: dict[str, object]

    @property
    def is_ready(self) -> bool:
        return self.is_authorized and bool(self.display_name) and self.daily_calorie_limit is not None


@dataclass(frozen=True, slots=True)
class PendingAnalysis:
    chat_id: int
    telegram_file_id: str
    telegram_file_unique_id: str
    caption_text: str
    correction_text: str
    analysis: MealAnalysis
    analysis_message_id: int | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class MealEntry:
    id: int
    chat_id: int
    local_date: str
    total_calories: int
    analysis: MealAnalysis
    created_at: str


@dataclass(frozen=True, slots=True)
class DailyCalories:
    local_date: str
    calories: int


@dataclass(frozen=True, slots=True)
class OpenAIUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    total_cost_usd: float
