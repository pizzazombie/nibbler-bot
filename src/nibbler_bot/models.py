from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class MealItem:
    name: str
    amount: str
    calories: int
    protein_g: float = 0.0
    fat_g: float = 0.0
    carbs_g: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NutritionTotals:
    calories: int = 0
    protein_g: float = 0.0
    fat_g: float = 0.0
    carbs_g: float = 0.0

    def add(self, other: "NutritionTotals") -> "NutritionTotals":
        return NutritionTotals(
            calories=self.calories + other.calories,
            protein_g=round(self.protein_g + other.protein_g, 1),
            fat_g=round(self.fat_g + other.fat_g, 1),
            carbs_g=round(self.carbs_g + other.carbs_g, 1),
        )


@dataclass(slots=True)
class MealAnalysis:
    items: list[MealItem]
    total_calories: int
    total_protein_g: float = 0.0
    total_fat_g: float = 0.0
    total_carbs_g: float = 0.0
    notes: list[str] = field(default_factory=list)
    confidence: str = "medium"

    def to_dict(self) -> dict[str, object]:
        return {
            "items": [item.to_dict() for item in self.items],
            "total_calories": self.total_calories,
            "total_protein_g": self.total_protein_g,
            "total_fat_g": self.total_fat_g,
            "total_carbs_g": self.total_carbs_g,
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
                protein_g=round(float(item.get("protein_g", 0) or 0), 1),
                fat_g=round(float(item.get("fat_g", 0) or 0), 1),
                carbs_g=round(float(item.get("carbs_g", 0) or 0), 1),
            )
            for item in raw_items
            if isinstance(item, dict)
        ]
        return cls(
            items=items,
            total_calories=int(payload.get("total_calories", 0)),
            total_protein_g=round(float(payload.get("total_protein_g", 0) or 0), 1),
            total_fat_g=round(float(payload.get("total_fat_g", 0) or 0), 1),
            total_carbs_g=round(float(payload.get("total_carbs_g", 0) or 0), 1),
            notes=[str(item) for item in payload.get("notes", []) if str(item).strip()],
            confidence=str(payload.get("confidence", "medium") or "medium"),
        )

    @property
    def primary_item_name(self) -> str:
        if not self.items:
            return "Meal"
        return self.items[0].name

    @property
    def nutrition_totals(self) -> NutritionTotals:
        return NutritionTotals(
            calories=self.total_calories,
            protein_g=self.total_protein_g,
            fat_g=self.total_fat_g,
            carbs_g=self.total_carbs_g,
        )


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
