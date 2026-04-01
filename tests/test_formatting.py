from __future__ import annotations

from nibbler_bot.formatting import format_analysis_message
from nibbler_bot.models import MealAnalysis, MealItem


def test_pending_analysis_message_mentions_projection() -> None:
    analysis = MealAnalysis(
        items=[
            MealItem(name="Baked trout", amount="80 g", calories=430),
            MealItem(name="Mashed potatoes", amount="120 g", calories=120),
        ],
        total_calories=550,
        notes=["Portion size estimated from the plate"],
        confidence="medium",
    )

    text = format_analysis_message(
        analysis=analysis,
        today_total=200,
        daily_limit=1800,
        is_saved=False,
        display_name="Lev",
    )

    assert "If saved:" in text
    assert "550 kcal" in text
    assert "Portion size estimated from the plate" in text
