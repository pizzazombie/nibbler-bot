from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import aiosqlite

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
            items=[
                MealItem(
                    name="Coke Zero",
                    amount="330 ml can",
                    calories=3,
                    protein_g=0,
                    fat_g=0,
                    carbs_g=0.2,
                )
            ],
            total_calories=3,
            total_protein_g=0,
            total_fat_g=0,
            total_carbs_g=0.2,
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
        daily_nutrition = await storage.get_daily_nutrition(chat_id=1, local_date="2026-04-01")
        assert daily_nutrition.calories == 3
        assert daily_nutrition.carbs_g == 0.2

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


def test_delete_user_data_removes_all_user_records(tmp_path) -> None:
    async def scenario() -> None:
        storage = Storage(str(tmp_path / "nibbler.db"))
        await storage.initialize()
        await storage.upsert_user_identity(chat_id=1, username="nibbler", first_name="Nib")
        await storage.set_authorized(chat_id=1, month_key="2026-04", default_daily_calorie_limit=1800)
        await storage.update_display_name(1, "Lev")
        await storage.update_daily_limit(1, 1900)

        analysis = MealAnalysis(
            items=[
                MealItem(
                    name="Coke Zero",
                    amount="330 ml can",
                    calories=3,
                    protein_g=0,
                    fat_g=0,
                    carbs_g=0.2,
                )
            ],
            total_calories=3,
            total_protein_g=0,
            total_fat_g=0,
            total_carbs_g=0.2,
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
        await storage.mark_report_delivery(
            chat_id=1,
            report_kind="weekly",
            report_period="2026-03-25_2026-03-31",
        )
        meal = await storage.confirm_pending_analysis(chat_id=1, local_date="2026-04-01")
        assert meal is not None

        assert await storage.delete_user_data(1) is True
        assert await storage.get_user(1) is None
        assert await storage.get_pending_analysis(1) is None
        assert await storage.list_meals_for_day(chat_id=1, local_date="2026-04-01") == []
        assert await storage.count_generations_for_day(chat_id=1, local_date="2026-04-01") == 0
        assert await storage.has_report_delivery(
            chat_id=1,
            report_kind="weekly",
            report_period="2026-03-25_2026-03-31",
        ) is False
        assert await storage.delete_user_data(1) is False

    asyncio.run(scenario())


def test_storage_lists_pending_items_ready_for_auto_confirm(tmp_path) -> None:
    async def scenario() -> None:
        storage = Storage(str(tmp_path / "nibbler.db"))
        await storage.initialize()
        await storage.upsert_user_identity(chat_id=1, username="nibbler", first_name="Nib")
        await storage.set_authorized(chat_id=1, month_key="2026-04", default_daily_calorie_limit=1800)

        analysis = MealAnalysis(
            items=[MealItem(name="Toast", amount="1 slice", calories=90, protein_g=3, fat_g=1, carbs_g=15)],
            total_calories=90,
            total_protein_g=3,
            total_fat_g=1,
            total_carbs_g=15,
            notes=[],
            confidence="high",
        )
        await storage.save_pending_analysis(
            chat_id=1,
            telegram_file_id="file-1",
            telegram_file_unique_id="uniq-1",
            caption_text="Breakfast",
            correction_text="",
            analysis=analysis,
        )

        old_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
        async with aiosqlite.connect(tmp_path / "nibbler.db") as db:
            await db.execute(
                "UPDATE pending_analyses SET updated_at = ? WHERE chat_id = ?",
                (old_timestamp, 1),
            )
            await db.commit()

        pending_items = await storage.list_pending_analyses_ready_for_auto_confirm(
            older_than_minutes=10
        )

        assert len(pending_items) == 1
        assert pending_items[0].chat_id == 1
        assert pending_items[0].updated_at == old_timestamp

    asyncio.run(scenario())


def test_text_only_pending_analysis_can_be_saved(tmp_path) -> None:
    async def scenario() -> None:
        storage = Storage(str(tmp_path / "nibbler.db"))
        await storage.initialize()
        await storage.upsert_user_identity(chat_id=1, username="nibbler", first_name="Nib")
        await storage.set_authorized(chat_id=1, month_key="2026-04", default_daily_calorie_limit=1800)

        analysis = MealAnalysis(
            items=[MealItem(name="Greek yogurt", amount="200 g", calories=146, protein_g=20, fat_g=5, carbs_g=8)],
            total_calories=146,
            total_protein_g=20,
            total_fat_g=5,
            total_carbs_g=8,
            notes=[],
            confidence="high",
        )
        await storage.save_pending_analysis(
            chat_id=1,
            telegram_file_id="",
            telegram_file_unique_id="",
            caption_text="200 g Greek yogurt",
            correction_text="",
            analysis=analysis,
        )

        pending = await storage.get_pending_analysis(1)
        assert pending is not None
        assert pending.telegram_file_id == ""
        meal = await storage.confirm_pending_analysis(chat_id=1, local_date="2026-04-01")
        assert meal is not None
        assert meal.total_calories == 146
        nutrition = await storage.get_daily_nutrition(chat_id=1, local_date="2026-04-01")
        assert nutrition.protein_g == 20
        assert nutrition.fat_g == 5
        assert nutrition.carbs_g == 8

    asyncio.run(scenario())
