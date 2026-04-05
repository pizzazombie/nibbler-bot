from __future__ import annotations

from datetime import date

from nibbler_bot.formatting import (
    build_delete_all_data_keyboard,
    build_main_keyboard,
    build_pending_keyboard,
    build_settings_keyboard,
    format_delete_all_data_confirmation_message,
    format_analysis_message,
    format_manual_monthly_chart_message,
    format_post_password_welcome_message,
)
from nibbler_bot.meal_analyzer import load_system_prompt
from nibbler_bot.models import DailyCalories, MealAnalysis, MealItem, NutritionTotals, UserProfile


def test_pending_analysis_message_mentions_projection() -> None:
    analysis = MealAnalysis(
        items=[
            MealItem(name="Baked trout", amount="80 g", calories=430, protein_g=26, fat_g=34, carbs_g=0),
            MealItem(
                name="Mashed potatoes",
                amount="120 g",
                calories=120,
                protein_g=3,
                fat_g=4,
                carbs_g=20,
            ),
        ],
        total_calories=550,
        total_protein_g=29,
        total_fat_g=38,
        total_carbs_g=20,
        notes=["Portion size estimated from the plate"],
        confidence="medium",
    )

    text = format_analysis_message(
        analysis=analysis,
        today_totals=NutritionTotals(calories=200, protein_g=10, fat_g=5, carbs_g=12),
        daily_limit=1800,
        is_saved=False,
        display_name="Lev",
    )

    assert "If saved:" in text
    assert "550 kcal" in text
    assert "P 29 g" in text
    assert "F 38 g" in text
    assert "C 20 g" in text
    assert "Portion size estimated from the plate" in text
    assert "auto-save this meal in 10 minutes" in text


def test_keyboards_include_chart_buttons() -> None:
    main_keyboard = build_main_keyboard()
    pending_keyboard = build_pending_keyboard()
    settings_keyboard = build_settings_keyboard()
    delete_all_data_keyboard = build_delete_all_data_keyboard()

    main_texts = [button.text for row in main_keyboard.keyboard for button in row]
    pending_texts = [button.text for row in pending_keyboard.inline_keyboard for button in row]
    settings_texts = [button.text for row in settings_keyboard.inline_keyboard for button in row]
    delete_all_texts = [
        button.text for row in delete_all_data_keyboard.inline_keyboard for button in row
    ]

    assert "📈 Week" in main_texts
    assert "🗓️ Month" in main_texts
    assert "💬 Add comment or fix" in pending_texts
    assert "📈 Weekly chart" in settings_texts
    assert "🗓️ Monthly chart" in settings_texts
    assert "🧨 Delete all my data" in settings_texts
    assert "🧨 Yes, delete everything" in delete_all_texts


def test_manual_month_message_mentions_same_span_comparison() -> None:
    user = UserProfile(
        chat_id=1,
        username="nibbler",
        first_name="Nib",
        display_name="Lev",
        daily_calorie_limit=1800,
        is_authorized=True,
        password_attempts=0,
        password_attempt_month="2026-04",
        onboarding_state=None,
        state_payload={},
    )
    text = format_manual_monthly_chart_message(
        user=user,
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 10),
        points=[DailyCalories(local_date="2026-04-01", calories=1500)],
        previous_points=[DailyCalories(local_date="2026-03-01", calories=1200)],
    )

    assert "Month so far" in text
    assert "same span last month" in text


def test_system_prompt_is_loaded_from_text_file() -> None:
    prompt = load_system_prompt()

    assert "piece of processed cheese" in prompt
    assert "glass of orange juice" in prompt
    assert "protein_g" in prompt


def test_post_password_welcome_message_explains_bot_capabilities() -> None:
    text = format_post_password_welcome_message()

    assert "Welcome to Nibbler bot" in text
    assert "estimate calories plus protein, fat, and carbs" in text
    assert "First, what should I call you?" in text


def test_delete_all_data_confirmation_message_mentions_full_reset() -> None:
    text = format_delete_all_data_confirmation_message()

    assert "Delete all data?" in text
    assert "saved meals" in text
    assert "/start" in text
