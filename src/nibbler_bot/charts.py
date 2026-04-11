from __future__ import annotations

import io
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from .models import DailyCalories, DailyNutrition, NutritionTotals


WIDTH = 1200
HEIGHT = 720
MARGIN_LEFT = 90
MARGIN_RIGHT = 40
MARGIN_TOP = 90
MARGIN_BOTTOM = 100
NUTRITION_COLORS = {
    "K": "#47a07a",
    "P": "#4f8cc9",
    "F": "#d99530",
    "C": "#9b6ad6",
}


def _font() -> ImageFont.ImageFont:
    return ImageFont.load_default()


def build_weekly_chart(
    *,
    points: list[DailyCalories],
    daily_limit: int,
    title: str,
    subtitle: str,
) -> bytes:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#fff8ee")
    draw = ImageDraw.Draw(image)
    font = _font()

    draw.rounded_rectangle((24, 24, WIDTH - 24, HEIGHT - 24), radius=26, fill="#fffdf9", outline="#f3dbc4")
    draw.text((MARGIN_LEFT, 36), title, fill="#2c241d", font=font)
    draw.text((MARGIN_LEFT, 56), subtitle, fill="#7f6a58", font=font)

    chart_left = MARGIN_LEFT
    chart_top = MARGIN_TOP
    chart_right = WIDTH - MARGIN_RIGHT
    chart_bottom = HEIGHT - MARGIN_BOTTOM
    chart_height = chart_bottom - chart_top
    chart_width = chart_right - chart_left

    max_calories = max([point.calories for point in points] + [daily_limit, 1000])
    padded_max = int(max_calories * 1.15)
    padded_max = max(padded_max, daily_limit + 200, 1000)

    for step in range(5):
        y = chart_bottom - int(chart_height * step / 4)
        value = int(padded_max * step / 4)
        draw.line((chart_left, y, chart_right, y), fill="#f0e4d8", width=2)
        draw.text((20, y - 6), f"{value}", fill="#8f7763", font=font)

    if daily_limit > 0:
        limit_y = chart_bottom - int(chart_height * daily_limit / padded_max)
        draw.line((chart_left, limit_y, chart_right, limit_y), fill="#d65454", width=3)
        draw.text((chart_right - 120, limit_y - 16), f"limit {daily_limit}", fill="#b44747", font=font)

    bar_count = max(len(points), 1)
    gap = 18
    bar_width = max(int((chart_width - gap * (bar_count - 1)) / bar_count), 28)
    start_x = chart_left + max(int((chart_width - (bar_width * bar_count + gap * (bar_count - 1))) / 2), 0)

    for index, point in enumerate(points):
        x0 = start_x + index * (bar_width + gap)
        x1 = x0 + bar_width
        bar_height = int(chart_height * point.calories / padded_max)
        y0 = chart_bottom - bar_height
        fill = "#47a07a" if point.calories <= daily_limit else "#ff8f70"
        draw.rounded_rectangle((x0, y0, x1, chart_bottom), radius=12, fill=fill)
        day_label = datetime.fromisoformat(point.local_date).strftime("%a")
        draw.text((x0 + 4, chart_bottom + 10), day_label, fill="#5b4b40", font=font)
        draw.text((x0 + 2, y0 - 18), str(point.calories), fill="#5b4b40", font=font)

    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def build_nutrition_chart(
    *,
    points: list[DailyNutrition],
    targets: NutritionTotals,
    title: str,
    subtitle: str,
) -> bytes:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#fff8ee")
    draw = ImageDraw.Draw(image)
    font = _font()

    draw.rounded_rectangle((24, 24, WIDTH - 24, HEIGHT - 24), radius=26, fill="#fffdf9", outline="#f3dbc4")
    draw.text((MARGIN_LEFT, 36), title, fill="#2c241d", font=font)
    draw.text((MARGIN_LEFT, 56), subtitle, fill="#7f6a58", font=font)

    chart_left = MARGIN_LEFT
    chart_right = WIDTH - MARGIN_RIGHT
    chart_width = chart_right - chart_left
    lane_gap = 18
    lane_count = 4
    lane_top = MARGIN_TOP
    lane_height = int((HEIGHT - MARGIN_TOP - MARGIN_BOTTOM - lane_gap * (lane_count - 1)) / lane_count)

    series = [
        ("K", "Calories", "kcal", [point.calories for point in points], max(targets.calories, 1)),
        ("P", "Protein", "g", [point.protein_g for point in points], max(targets.protein_g, 1)),
        ("F", "Fat", "g", [point.fat_g for point in points], max(targets.fat_g, 1)),
        ("C", "Carbs", "g", [point.carbs_g for point in points], max(targets.carbs_g, 1)),
    ]

    bar_count = max(len(points), 1)
    gap = 14
    bar_width = max(int((chart_width - gap * (bar_count - 1)) / bar_count), 24)
    start_x = chart_left + max(int((chart_width - (bar_width * bar_count + gap * (bar_count - 1))) / 2), 0)

    for lane_index, (letter, label, unit, values, limit) in enumerate(series):
        top = lane_top + lane_index * (lane_height + lane_gap)
        bottom = top + lane_height
        max_value = max([float(value) for value in values] + [float(limit)])
        padded_max = max(max_value * 1.2, float(limit) * 1.15, 1)
        color = NUTRITION_COLORS[letter]

        draw.text((20, top + 4), label, fill="#5b4b40", font=font)
        draw.line((chart_left, bottom, chart_right, bottom), fill="#f0e4d8", width=2)
        limit_y = bottom - int(lane_height * float(limit) / padded_max)
        draw.line((chart_left, limit_y, chart_right, limit_y), fill="#d65454", width=2)
        draw.text((chart_right - 150, limit_y - 14), f"{letter} limit {format_limit(limit)}{unit}", fill="#b44747", font=font)

        for index, value in enumerate(values):
            x0 = start_x + index * (bar_width + gap)
            x1 = x0 + bar_width
            bar_height = int(lane_height * float(value) / padded_max)
            y0 = bottom - bar_height
            draw.rounded_rectangle((x0, y0, x1, bottom), radius=8, fill=color)
            if bar_height > 18:
                draw.text((x0 + max(int(bar_width / 2) - 3, 2), y0 + 4), letter, fill="#fffdf9", font=font)
            draw.text((x0 + 2, max(y0 - 14, top)), format_limit(value), fill="#5b4b40", font=font)
            if lane_index == lane_count - 1:
                day_label = datetime.fromisoformat(points[index].local_date).strftime("%a")
                draw.text((x0 + 4, bottom + 10), day_label, fill="#5b4b40", font=font)

    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def format_limit(value: float) -> str:
    rounded = round(float(value), 1)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.1f}"
