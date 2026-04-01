from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


MODEL_PRICING_DEFAULTS: dict[str, tuple[float, float, float]] = {
    "gpt-5.4": (2.50, 0.25, 15.00),
    "gpt-5.4-mini": (0.75, 0.08, 4.50),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
}


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Environment variable {name} is required")
    return value


def _optional_str(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _optional_float(name: str) -> float | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    return float(value)


def _optional_int_set(name: str) -> frozenset[int]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return frozenset()
    values: list[int] = []
    for item in raw.split(","):
        normalized = item.strip()
        if normalized:
            values.append(int(normalized))
    return frozenset(values)


@dataclass(frozen=True, slots=True)
class PricingConfig:
    input_per_1m_usd: float
    cached_input_per_1m_usd: float
    output_per_1m_usd: float

    def estimate_cost_usd(
        self,
        *,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
    ) -> float:
        uncached_input_tokens = max(input_tokens - cached_input_tokens, 0)
        return round(
            (uncached_input_tokens / 1_000_000 * self.input_per_1m_usd)
            + (cached_input_tokens / 1_000_000 * self.cached_input_per_1m_usd)
            + (output_tokens / 1_000_000 * self.output_per_1m_usd),
            6,
        )


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    openai_api_key: str
    access_password: str
    timezone_name: str
    database_path: str
    openai_model: str
    openai_reasoning_effort: str | None
    openai_max_output_tokens: int
    openai_request_timeout_seconds: int
    default_daily_calorie_limit: int
    daily_generation_limit: int
    weekly_summary_hour: int
    weekly_summary_minute: int
    monthly_summary_hour: int
    monthly_summary_minute: int
    admin_chat_ids: frozenset[int]
    pricing: PricingConfig

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


def _resolve_pricing(model: str) -> PricingConfig:
    defaults = MODEL_PRICING_DEFAULTS.get(model, (0.75, 0.08, 4.50))
    input_price = _optional_float("OPENAI_PRICE_INPUT_PER_1M_USD")
    cached_input_price = _optional_float("OPENAI_PRICE_CACHED_INPUT_PER_1M_USD")
    output_price = _optional_float("OPENAI_PRICE_OUTPUT_PER_1M_USD")
    return PricingConfig(
        input_per_1m_usd=input_price if input_price is not None else defaults[0],
        cached_input_per_1m_usd=(
            cached_input_price if cached_input_price is not None else defaults[1]
        ),
        output_per_1m_usd=output_price if output_price is not None else defaults[2],
    )


def load_settings() -> Settings:
    model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip()
    return Settings(
        telegram_bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
        openai_api_key=_require_env("OPENAI_API_KEY"),
        access_password=_require_env("ACCESS_PASSWORD"),
        timezone_name=os.getenv("TIMEZONE", "Europe/Madrid").strip(),
        database_path=os.getenv("DATABASE_PATH", "/data/nibbler-bot.db").strip(),
        openai_model=model,
        openai_reasoning_effort=_optional_str("OPENAI_REASONING_EFFORT") or "low",
        openai_max_output_tokens=int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "800")),
        openai_request_timeout_seconds=int(os.getenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "60")),
        default_daily_calorie_limit=int(os.getenv("DEFAULT_DAILY_CALORIE_LIMIT", "1800")),
        daily_generation_limit=int(os.getenv("DAILY_GENERATION_LIMIT", "100")),
        weekly_summary_hour=int(os.getenv("WEEKLY_SUMMARY_HOUR", "9")),
        weekly_summary_minute=int(os.getenv("WEEKLY_SUMMARY_MINUTE", "0")),
        monthly_summary_hour=int(os.getenv("MONTHLY_SUMMARY_HOUR", "9")),
        monthly_summary_minute=int(os.getenv("MONTHLY_SUMMARY_MINUTE", "5")),
        admin_chat_ids=_optional_int_set("ADMIN_CHAT_IDS"),
        pricing=_resolve_pricing(model),
    )
