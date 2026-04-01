from __future__ import annotations

import io
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from .models import DailyCalories


WIDTH = 1200
HEIGHT = 720
MARGIN_LEFT = 90
MARGIN_RIGHT = 40
MARGIN_TOP = 90
MARGIN_BOTTOM = 100


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
