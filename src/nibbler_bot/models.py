from __future__ import annotations

from dataclasses import asdict, dataclass, field


NUTRITION_GOALS: dict[str, tuple[str, tuple[float, float, float]]] = {
    "lose": ("lose fat", (0.30, 0.25, 0.45)),
    "maintain": ("maintain weight", (0.25, 0.30, 0.45)),
    "gain": ("build muscle", (0.25, 0.25, 0.50)),
}
DEFAULT_FIBER_LIMIT_G = 30


def normalize_nutrition_goal(goal: str | None) -> str:
    normalized = (goal or "").strip().lower()
    if normalized in NUTRITION_GOALS:
        return normalized
    return "maintain"


def calculate_macro_limits(calorie_limit: int, goal: str | None) -> "NutritionTotals":
    normalized_goal = normalize_nutrition_goal(goal)
    protein_ratio, fat_ratio, carbs_ratio = NUTRITION_GOALS[normalized_goal][1]
    return NutritionTotals(
        calories=calorie_limit,
        protein_g=round(calorie_limit * protein_ratio / 4),
        fat_g=round(calorie_limit * fat_ratio / 9),
        carbs_g=round(calorie_limit * carbs_ratio / 4),
        fiber_g=DEFAULT_FIBER_LIMIT_G,
    )


@dataclass(slots=True)
class MealItem:
    name: str
    amount: str
    calories: int
    count_estimate: float | None = None
    unit_label: str | None = None
    estimated_weight_g: float | None = None
    estimated_volume_ml: float | None = None
    protein_g: float = 0.0
    fat_g: float = 0.0
    carbs_g: float = 0.0
    fiber_g: float = 0.0
    estimation_basis: str | None = None
    item_confidence: str = "medium"
    reasoning_note_short: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NutritionTotals:
    calories: int = 0
    protein_g: float = 0.0
    fat_g: float = 0.0
    carbs_g: float = 0.0
    fiber_g: float = 0.0

    def add(self, other: "NutritionTotals") -> "NutritionTotals":
        return NutritionTotals(
            calories=self.calories + other.calories,
            protein_g=round(self.protein_g + other.protein_g, 1),
            fat_g=round(self.fat_g + other.fat_g, 1),
            carbs_g=round(self.carbs_g + other.carbs_g, 1),
            fiber_g=round(self.fiber_g + other.fiber_g, 1),
        )


@dataclass(slots=True)
class MealAnalysis:
    items: list[MealItem]
    total_calories: int
    total_protein_g: float = 0.0
    total_fat_g: float = 0.0
    total_carbs_g: float = 0.0
    total_fiber_g: float = 0.0
    notes: list[str] = field(default_factory=list)
    confidence: str = "medium"
    follow_up_question: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "items": [item.to_dict() for item in self.items],
            "total_calories": self.total_calories,
            "total_protein_g": self.total_protein_g,
            "total_fat_g": self.total_fat_g,
            "total_carbs_g": self.total_carbs_g,
            "total_fiber_g": self.total_fiber_g,
            "notes": list(self.notes),
            "confidence": self.confidence,
            "follow_up_question": self.follow_up_question,
        }

    @staticmethod
    def _optional_str(value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "MealAnalysis":
        raw_items = payload.get("items", [])
        items = [
            MealItem(
                name=str(item.get("name", "")),
                amount=str(item.get("amount", "")),
                calories=int(item.get("calories", 0)),
                count_estimate=(
                    round(float(item.get("count_estimate", 0) or 0), 1)
                    if item.get("count_estimate") is not None
                    else None
                ),
                unit_label=cls._optional_str(item.get("unit_label")),
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
                estimation_basis=cls._optional_str(item.get("estimation_basis")),
                item_confidence=str(item.get("item_confidence", "medium") or "medium"),
                reasoning_note_short=cls._optional_str(item.get("reasoning_note_short")),
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
            total_fiber_g=round(float(payload.get("total_fiber_g", 0) or 0), 1),
            notes=[str(item) for item in payload.get("notes", []) if str(item).strip()],
            confidence=str(payload.get("confidence", "medium") or "medium"),
            follow_up_question=str(payload.get("follow_up_question", "") or "").strip(),
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
            fiber_g=self.total_fiber_g,
        )


@dataclass(frozen=True, slots=True)
class UserProfile:
    chat_id: int
    username: str | None
    first_name: str | None
    display_name: str | None
    daily_calorie_limit: int | None
    nutrition_goal: str | None
    protein_limit_g: int | None
    fat_limit_g: int | None
    carbs_limit_g: int | None
    fiber_limit_g: int | None
    is_authorized: bool
    password_attempts: int
    password_attempt_month: str | None
    onboarding_state: str | None
    state_payload: dict[str, object]

    @property
    def is_ready(self) -> bool:
        return (
            self.is_authorized
            and bool(self.display_name)
            and self.daily_calorie_limit is not None
            and self.protein_limit_g is not None
            and self.fat_limit_g is not None
            and self.carbs_limit_g is not None
            and self.fiber_limit_g is not None
            and self.onboarding_state is None
        )

    @property
    def nutrition_targets(self) -> NutritionTotals:
        calorie_limit = self.daily_calorie_limit or 0
        default_targets = calculate_macro_limits(calorie_limit, self.nutrition_goal)
        return NutritionTotals(
            calories=calorie_limit,
            protein_g=self.protein_limit_g if self.protein_limit_g is not None else default_targets.protein_g,
            fat_g=self.fat_limit_g if self.fat_limit_g is not None else default_targets.fat_g,
            carbs_g=self.carbs_limit_g if self.carbs_limit_g is not None else default_targets.carbs_g,
            fiber_g=self.fiber_limit_g if self.fiber_limit_g is not None else default_targets.fiber_g,
        )


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
class DailyNutrition:
    local_date: str
    calories: int
    protein_g: float
    fat_g: float
    carbs_g: float
    fiber_g: float

    @property
    def nutrition_totals(self) -> NutritionTotals:
        return NutritionTotals(
            calories=self.calories,
            protein_g=self.protein_g,
            fat_g=self.fat_g,
            carbs_g=self.carbs_g,
            fiber_g=self.fiber_g,
        )


@dataclass(frozen=True, slots=True)
class OpenAIUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    total_cost_usd: float
