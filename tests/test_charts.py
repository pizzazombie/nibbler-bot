from __future__ import annotations

from nibbler_bot.charts import build_weekly_chart
from nibbler_bot.models import DailyCalories


def test_weekly_chart_is_png() -> None:
    chart = build_weekly_chart(
        points=[
            DailyCalories(local_date="2026-03-23", calories=1500),
            DailyCalories(local_date="2026-03-24", calories=1720),
            DailyCalories(local_date="2026-03-25", calories=1900),
            DailyCalories(local_date="2026-03-26", calories=1650),
            DailyCalories(local_date="2026-03-27", calories=1800),
            DailyCalories(local_date="2026-03-28", calories=2200),
            DailyCalories(local_date="2026-03-29", calories=1400),
        ],
        daily_limit=1800,
        title="Nibbler weekly calories",
        subtitle="2026-03-23 to 2026-03-29",
    )

    assert chart.startswith(b"\x89PNG")
    assert len(chart) > 1000
