from __future__ import annotations

import asyncio

from nibbler_bot.models import MealAnalysis, MealItem
from nibbler_bot.storage import Storage


def test_storage_flow(tmp_path) -> None:
    async def scenario() -> None:
        storage = Storage(str(tmp_path / "nibbler.db"))
        await storage.initialize()
        await storage.upsert_user_identity(chat_id=1, username="nibbler", first_name="Nib")
        await storage.set_authorized(chat_id=1, month_key="2026-04", default_daily_calorie_limit=1800)
        await storage.update_display_name(1, "Lev")
        await storage.update_daily_limit(1, 1900)

        analysis = MealAnalysis(
            items=[MealItem(name="Coke Zero", amount="330 ml can", calories=3)],
            total_calories=3,
            notes=["Recognized as a zero-sugar soda"],
            confidence="high",
        )
        await storage.save_pending_analysis(
            chat_id=1,
            telegram_file_id="file-1",
            telegram_file_unique_id="uniq-1",
            caption_text="Lunch",
            correction_text="",
            analysis=analysis,
        )
        pending = await storage.get_pending_analysis(1)
        assert pending is not None
        assert pending.analysis.total_calories == 3

        meal = await storage.confirm_pending_analysis(chat_id=1, local_date="2026-04-01")
        assert meal is not None
        assert meal.total_calories == 3
        assert await storage.get_pending_analysis(1) is None
        assert await storage.get_daily_total(chat_id=1, local_date="2026-04-01") == 3

        await storage.record_openai_usage(
            chat_id=1,
            local_date="2026-04-01",
            request_kind="meal_analysis",
            model="gpt-5.4-mini",
            input_tokens=100,
            cached_input_tokens=10,
            output_tokens=40,
            total_cost_usd=0.001,
        )
        await storage.record_openai_usage(
            chat_id=1,
            local_date="2026-03-31",
            request_kind="meal_analysis",
            model="gpt-5.4-mini",
            input_tokens=50,
            cached_input_tokens=0,
            output_tokens=20,
            total_cost_usd=0.002,
        )
        assert await storage.count_generations_for_day(chat_id=1, local_date="2026-04-01") == 1
        assert await storage.get_openai_usage_summary() == (2, 0.003)
        assert await storage.get_openai_usage_summary_for_month("2026-04") == (1, 0.001)

    asyncio.run(scenario())
