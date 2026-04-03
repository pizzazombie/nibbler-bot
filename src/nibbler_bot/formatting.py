from __future__ import annotations

import html
from datetime import date, datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .models import DailyCalories, MealAnalysis, MealEntry, UserProfile


def build_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("⚙️ Settings"), KeyboardButton("📊 Today")],
            [KeyboardButton("📈 Week"), KeyboardButton("🗓️ Month")],
        ],
        resize_keyboard=True,
    )


def build_pending_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Save meal", callback_data="meal:save"),
                InlineKeyboardButton("❌ Ignore", callback_data="meal:discard"),
            ],
            [
                InlineKeyboardButton("💬 Add comment or fix", callback_data="meal:fix_hint"),
                InlineKeyboardButton("⚙️ Settings", callback_data="settings:open"),
            ],
        ]
    )


def build_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Change name", callback_data="settings:name")],
            [InlineKeyboardButton("🎯 Change daily limit", callback_data="settings:limit")],
            [InlineKeyboardButton("🗑️ Delete a meal from today", callback_data="settings:delete")],
            [InlineKeyboardButton("🧨 Delete all my data", callback_data="settings:wipe")],
            [InlineKeyboardButton("📊 Show today", callback_data="settings:today")],
            [InlineKeyboardButton("📈 Weekly chart", callback_data="settings:week")],
            [InlineKeyboardButton("🗓️ Monthly chart", callback_data="settings:month")],
            [InlineKeyboardButton("✖️ Close", callback_data="settings:close")],
        ]
    )


def build_delete_all_data_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧨 Yes, delete everything", callback_data="settings:wipe:confirm")],
            [InlineKeyboardButton("⬅️ Back", callback_data="settings:open")],
        ]
    )


def build_delete_meal_keyboard(meals: list[MealEntry]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"🗑️ {build_meal_short_label(meal)}",
                callback_data=f"settings:delete:{meal.id}",
            )
        ]
        for meal in meals[:10]
    ]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="settings:open")])
    return InlineKeyboardMarkup(rows)


def build_meal_short_label(meal: MealEntry) -> str:
    clock = datetime.fromisoformat(meal.created_at).strftime("%H:%M")
    title = meal.analysis.primary_item_name
    safe_title = title if len(title) <= 24 else f"{title[:21]}..."
    return f"{meal.total_calories} kcal • {clock} • {safe_title}"


def format_help_message() -> str:
    return (
        "👋 <b>Nibbler bot</b>\n\n"
        "Send exactly one food or drink photo per message. You can also add a short caption like "
        "<i>\"and a glass of champagne\"</i>.\n\n"
        "After the estimate arrives, only these actions count:\n"
        "• tap <b>✅ Save meal</b> to add it to today\n"
        "• tap <b>❌ Ignore</b> to discard it\n"
        "• send a comment like <i>\"It was Coke Zero\"</i> or <i>\"also a glass of orange juice\"</i> "
        "to re-run the same photo\n\n"
        "Important:\n"
        "• if you send a new photo, the old pending estimate is replaced\n"
        "• if you send several photos as an album, I will ask for one at a time\n"
        "• only saved meals affect your daily total\n\n"
        "Use <b>⚙️ Settings</b> to change your name, change your daily calorie goal, or delete a meal "
        "that was saved by mistake.\n"
        "Use <b>📈 Week</b> or <b>🗓️ Month</b> to pull your charts on demand.\n\n"
        "Friendly note: all estimates are approximate. Packaged products are usually more accurate than "
        "mixed plates."
    )


def format_post_password_welcome_message() -> str:
    return (
        "👋 <b>Welcome to Nibbler bot</b>\n\n"
        "I help you track calories from food and drink photos, plus short text notes.\n\n"
        "Here is what I can do:\n"
        "• estimate calories from one meal photo at a time\n"
        "• include extra details like <i>\"also a glass of orange juice\"</i>\n"
        "• let you save, ignore, or correct each estimate before it counts\n"
        "• keep your daily total and show weekly or monthly charts\n\n"
        "First, what should I call you?"
    )


def format_settings_message(user: UserProfile, today_total: int) -> str:
    name = html.escape(user.display_name or user.first_name or "there")
    limit = user.daily_calorie_limit or 0
    return (
        f"⚙️ <b>Settings</b>\n\n"
        f"<b>Name:</b> {name}\n"
        f"<b>Daily limit:</b> {limit} kcal\n"
        f"<b>Saved today:</b> {today_total} / {limit} kcal"
    )


def format_delete_all_data_confirmation_message() -> str:
    return (
        "🧨 <b>Delete all data?</b>\n\n"
        "This will permanently delete your profile, saved meals, pending estimate, calorie history, "
        "and your personal usage stats.\n\n"
        "After that, you will need to start again from <b>/start</b>."
    )


def format_today_message(user: UserProfile, today_total: int, meals: list[MealEntry]) -> str:
    limit = user.daily_calorie_limit or 0
    lines = [
        "📊 <b>Today</b>",
        "",
        f"<b>Saved:</b> {today_total} / {limit} kcal",
    ]
    if meals:
        lines.extend(["", "<b>Meals:</b>"])
        for meal in meals[:8]:
            lines.append(
                f"• {html.escape(meal.analysis.primary_item_name)} — {meal.total_calories} kcal"
            )
    else:
        lines.extend(["", "No saved meals yet."])
    return "\n".join(lines)


def format_analysis_message(
    *,
    analysis: MealAnalysis,
    today_total: int,
    daily_limit: int,
    is_saved: bool,
    display_name: str,
) -> str:
    header = "✅ <b>Meal saved</b>" if is_saved else "🍽️ <b>Estimated meal</b>"
    lines = [header, ""]
    if analysis.items:
        for item in analysis.items:
            amount = html.escape(item.amount or "estimated portion")
            name = html.escape(item.name or "Item")
            lines.append(f"• {name} — {amount}: <b>{item.calories} kcal</b>")
    else:
        lines.append("• I could not confidently identify the meal from this photo.")
    lines.extend(
        [
            "",
            f"<b>Total:</b> {analysis.total_calories} kcal",
        ]
    )
    if is_saved:
        lines.append(f"<b>Today:</b> {today_total} / {daily_limit} kcal")
    else:
        projected_total = today_total + analysis.total_calories
        lines.append(f"<b>Saved today:</b> {today_total} / {daily_limit} kcal")
        lines.append(f"<b>If saved:</b> {projected_total} / {daily_limit} kcal")
    if analysis.notes:
        lines.extend(["", "<b>Notes:</b>"])
        for note in analysis.notes[:3]:
            lines.append(f"• {html.escape(note)}")
    if not is_saved:
        lines.extend(
            [
                "",
                "💬 Send any comment or correction and I'll include it in the next estimate.",
                "⏱️ If you do nothing, I'll auto-save this meal in 10 minutes.",
            ]
        )
    return "\n".join(lines)


def format_meal_deleted_message(
    *,
    meal: MealEntry,
    today_total: int,
    daily_limit: int,
) -> str:
    return (
        "🗑️ <b>Meal deleted</b>\n\n"
        f"Removed: {html.escape(meal.analysis.primary_item_name)} — <b>{meal.total_calories} kcal</b>\n"
        f"Today: <b>{today_total} / {daily_limit} kcal</b>"
    )


def format_weekly_summary_message(
    *,
    user: UserProfile,
    start_date: date,
    end_date: date,
    points: list[DailyCalories],
) -> str:
    total = sum(point.calories for point in points)
    limit = user.daily_calorie_limit or 0
    over_limit_days = sum(1 for point in points if point.calories > limit)
    average = round(total / max(len(points), 1))
    return (
        "📈 <b>Your weekly calorie recap</b>\n\n"
        f"{start_date.isoformat()} to {end_date.isoformat()}\n"
        f"Total: <b>{total} kcal</b>\n"
        f"Average per day: <b>{average} kcal</b>\n"
        f"Days over limit: <b>{over_limit_days}</b> / {len(points)}"
    )


def format_monthly_summary_message(
    *,
    user: UserProfile,
    month_label: str,
    points: list[DailyCalories],
    previous_points: list[DailyCalories],
) -> str:
    total = sum(point.calories for point in points)
    previous_total = sum(point.calories for point in previous_points)
    average = round(total / max(len(points), 1))
    delta = total - previous_total
    limit = user.daily_calorie_limit or 0
    over_limit_days = sum(1 for point in points if point.calories > limit)
    trend = "up" if delta > 0 else "down" if delta < 0 else "flat"
    return (
        "🗓️ <b>Monthly calorie trend</b>\n\n"
        f"Month: <b>{html.escape(month_label)}</b>\n"
        f"Total: <b>{total} kcal</b>\n"
        f"Average per day: <b>{average} kcal</b>\n"
        f"Days over limit: <b>{over_limit_days}</b>\n"
        f"Trend vs previous month: <b>{trend}</b> ({delta:+d} kcal)"
    )


def format_manual_monthly_chart_message(
    *,
    user: UserProfile,
    start_date: date,
    end_date: date,
    points: list[DailyCalories],
    previous_points: list[DailyCalories],
) -> str:
    total = sum(point.calories for point in points)
    previous_total = sum(point.calories for point in previous_points)
    average = round(total / max(len(points), 1))
    delta = total - previous_total
    limit = user.daily_calorie_limit or 0
    over_limit_days = sum(1 for point in points if point.calories > limit)
    trend = "up" if delta > 0 else "down" if delta < 0 else "flat"
    return (
        "🗓️ <b>Month so far</b>\n\n"
        f"{start_date.isoformat()} to {end_date.isoformat()}\n"
        f"Total: <b>{total} kcal</b>\n"
        f"Average per day: <b>{average} kcal</b>\n"
        f"Days over limit: <b>{over_limit_days}</b>\n"
        f"Trend vs same span last month: <b>{trend}</b> ({delta:+d} kcal)"
    )
