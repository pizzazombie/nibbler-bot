from __future__ import annotations

import calendar
import logging
import re
from datetime import date, datetime, time, timedelta
from html import escape

from pathlib import Path

from telegram import BotCommand, BotCommandScopeChat, InputFile, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .charts import build_weekly_chart
from .config import Settings
from .formatting import (
    build_delete_all_data_keyboard,
    build_delete_meal_keyboard,
    build_main_keyboard,
    build_nutrition_goal_keyboard,
    build_pending_keyboard,
    build_settings_keyboard,
    format_delete_all_data_confirmation_message,
    format_analysis_message,
    format_help_message,
    format_manual_monthly_chart_message,
    format_meal_deleted_message,
    format_monthly_summary_message,
    format_post_password_welcome_message,
    format_settings_message,
    format_today_message,
    format_weekly_summary_message,
)
from .meal_analyzer import MealAnalyzer
from .monitoring import MonitoringService
from .models import NUTRITION_GOALS, MealEntry, PendingAnalysis, UserProfile, normalize_nutrition_goal
from .storage import Storage


LOGGER = logging.getLogger(__name__)
AUTO_CONFIRM_PENDING_MINUTES = 10
INTRO_STICKER_FILE_ID = (
    "AAMCAgADGQEAAxppzkVlVj8jQfI1RuixLRkt5xyHJAAC15kAAk4vcEqLAWw2HmKH1QEAB20AAzoE"
)
SHIPPED_STICKER_FILE_ID = (
    "AAMCAQADGQEAAxlpzVyOyaTF7lJazf6ZWCnQDt8wRAACrQEAAhfVwUaXJFDkHgUoqQEAB20AAzoE"
)


def build_bot_commands() -> list[BotCommand]:
    return [
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Show instructions"),
        BotCommand("today", "Show today's calories"),
        BotCommand("settings", "Open settings"),
    ]


def build_admin_bot_commands() -> list[BotCommand]:
    return build_bot_commands() + [
        BotCommand("health", "Admin: service health"),
        BotCommand("server", "Admin: server resources"),
        BotCommand("containers", "Admin: Docker containers"),
    ]


def month_key(now: datetime) -> str:
    return f"{now.year:04d}-{now.month:02d}"


def local_now(settings: Settings) -> datetime:
    return datetime.now(settings.timezone)


def local_today(settings: Settings) -> str:
    return local_now(settings).date().isoformat()


def previous_month_bounds(anchor: date) -> tuple[date, date]:
    if anchor.month == 1:
        year = anchor.year - 1
        month = 12
    else:
        year = anchor.year
        month = anchor.month - 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def current_month_bounds(anchor: date) -> tuple[date, date]:
    last_day = calendar.monthrange(anchor.year, anchor.month)[1]
    return date(anchor.year, anchor.month, 1), date(anchor.year, anchor.month, last_day)


def month_to_date_bounds(anchor: date) -> tuple[date, date]:
    return date(anchor.year, anchor.month, 1), anchor


def describe_blocked_month(now: datetime) -> str:
    month_name = now.strftime("%B %Y")
    return month_name


def register_handlers(
    application: Application,
    *,
    settings: Settings,
    storage: Storage,
    analyzer: MealAnalyzer,
    monitoring: MonitoringService,
) -> None:
    seen_media_groups: dict[str, datetime] = {}

    async def ensure_private_chat(update: Update) -> bool:
        chat = update.effective_chat
        if chat is None:
            return False
        if chat.type == "private":
            return True
        if update.effective_message is not None:
            await update.effective_message.reply_text(
                "Nibbler bot works in private chats only.",
                reply_markup=build_main_keyboard(),
            )
        elif update.callback_query is not None:
            await update.callback_query.answer("Use me in a private chat.", show_alert=True)
        return False

    async def ensure_user(update: Update) -> UserProfile | None:
        if update.effective_chat is None or update.effective_user is None:
            return None
        await storage.upsert_user_identity(
            chat_id=update.effective_chat.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
        )
        user = await storage.get_user(update.effective_chat.id)
        if user is None:
            return None
        if not user.is_authorized:
            now = local_now(settings)
            current_month = month_key(now)
            if user.password_attempt_month != current_month and user.password_attempts != 0:
                await storage.update_password_attempts(
                    chat_id=user.chat_id,
                    attempts=0,
                    month_key=current_month,
                    authorized=False,
                )
                user = await storage.get_user(update.effective_chat.id)
        return user

    async def send_welcome_or_password_prompt(message, user: UserProfile) -> None:
        if user.is_authorized:
            if user.is_ready:
                await message.reply_text(
                    (
                        f"Hey {escape(user.display_name or 'there')} 👋\n\n"
                        "Send one food photo or describe the meal in text and I’ll estimate the calories. "
                        "Only meals saved with ✅ count toward today."
                    ),
                    parse_mode=ParseMode.HTML,
                    reply_markup=build_main_keyboard(),
                )
                return
            if user.onboarding_state == "awaiting_name":
                await message.reply_text(
                    "Welcome to Nibbler bot 🍽️\n\nWhat should I call you?",
                    reply_markup=build_main_keyboard(),
                )
                return
            if user.onboarding_state == "awaiting_goal":
                await message.reply_text(
                    (
                        "What are you using Nibbler for?\n\n"
                        "I’ll use this to calculate starter protein/fat/carbs limits from your calorie goal. "
                        "You can change macro limits later in Settings."
                    ),
                    reply_markup=build_nutrition_goal_keyboard(),
                )
                return
            if user.onboarding_state == "awaiting_macro_limits_update":
                await message.reply_text(
                    "Send macro limits as three numbers: protein fat carbs. Example: 120 55 180.",
                    reply_markup=build_main_keyboard(),
                )
                return
            await message.reply_text(
                "What daily calorie target should I use for you? Please send a whole number, for example 1800.",
                reply_markup=build_main_keyboard(),
            )
            return

        now = local_now(settings)
        current_month = month_key(now)
        if user.password_attempt_month != current_month:
            attempts = 0
        else:
            attempts = user.password_attempts
        if attempts >= 3:
            await message.reply_text(
                (
                    "🔒 Access is locked for now.\n\n"
                    f"You used all 3 password attempts for {describe_blocked_month(now)}. "
                    "Try again next month."
                )
            )
            return
        await message.reply_text(
            "🔐 Please enter the access password. You get 3 attempts per month."
        )

    async def ensure_ready_user(update: Update) -> UserProfile | None:
        if not await ensure_private_chat(update):
            return None
        user = await ensure_user(update)
        if user is None:
            return None
        if not user.is_authorized:
            if update.effective_message is not None:
                await send_welcome_or_password_prompt(update.effective_message, user)
            return None
        if not user.is_ready:
            if update.effective_message is not None:
                await send_welcome_or_password_prompt(update.effective_message, user)
            return None
        return user

    def is_admin(chat_id: int) -> bool:
        return chat_id in settings.admin_chat_ids

    async def ensure_admin(update: Update) -> UserProfile | None:
        user = await ensure_ready_user(update)
        if user is None:
            return None
        if is_admin(user.chat_id):
            return user
        if update.effective_message is not None:
            await update.effective_message.reply_text("This command is available only to the admin.")
        elif update.callback_query is not None:
            await update.callback_query.answer("Admin only.", show_alert=True)
        return None

    async def edit_or_send_pending_message(
        *,
        chat_id: int,
        thread_message,
        pending: PendingAnalysis | None,
        text: str,
    ) -> int | None:
        if pending and pending.analysis_message_id:
            try:
                await application.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=pending.analysis_message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=build_pending_keyboard(),
                )
                return pending.analysis_message_id
            except BadRequest:
                LOGGER.info("Pending message could not be edited for chat %s", chat_id)
        sent = await thread_message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=build_pending_keyboard(),
        )
        return sent.message_id

    async def supersede_previous_pending(chat_id: int, pending: PendingAnalysis | None) -> None:
        if pending is None or pending.analysis_message_id is None:
            return
        try:
            await application.bot.edit_message_text(
                chat_id=chat_id,
                message_id=pending.analysis_message_id,
                text="🆕 This estimate was replaced by a newer meal input.",
            )
        except BadRequest:
            LOGGER.info("Could not mark previous pending estimate as replaced in chat %s", chat_id)

    def photo_mime_type(file_path: str | None) -> str:
        if not file_path:
            return "image/jpeg"
        lower = file_path.lower()
        if lower.endswith(".png"):
            return "image/png"
        if lower.endswith(".webp"):
            return "image/webp"
        return "image/jpeg"

    async def can_generate(user: UserProfile, message) -> bool:
        generation_count = await storage.count_generations_for_day(
            chat_id=user.chat_id,
            local_date=local_today(settings),
        )
        if generation_count < settings.daily_generation_limit:
            return True
        await message.reply_text(
            (
                "You hit the daily analysis limit for today.\n\n"
                f"Limit: {settings.daily_generation_limit} OpenAI generations per day."
            ),
            reply_markup=build_main_keyboard(),
        )
        return False

    async def analyze_meal_input(
        *,
        message,
        user: UserProfile,
        telegram_file_id: str,
        telegram_file_unique_id: str,
        caption_text: str,
        correction_text: str,
        previous_pending: PendingAnalysis | None,
    ) -> None:
        if not await can_generate(user, message):
            return
        await supersede_previous_pending(user.chat_id, previous_pending)
        await application.bot.send_chat_action(chat_id=user.chat_id, action=ChatAction.TYPING)
        status_message = await message.reply_text("🔎 Estimating meal...")
        try:
            image_bytes: bytes | None = None
            mime_type: str | None = None
            if telegram_file_id:
                telegram_file = await application.bot.get_file(telegram_file_id)
                image_bytes = bytes(await telegram_file.download_as_bytearray())
                mime_type = photo_mime_type(telegram_file.file_path)
            result = await analyzer.analyze(
                image_bytes=image_bytes,
                mime_type=mime_type,
                caption_text=caption_text,
                correction_text=correction_text,
            )
            await storage.record_openai_usage(
                chat_id=user.chat_id,
                local_date=local_today(settings),
                request_kind="meal_analysis",
                model=settings.openai_model,
                input_tokens=result.usage.input_tokens,
                cached_input_tokens=result.usage.cached_input_tokens,
                output_tokens=result.usage.output_tokens,
                total_cost_usd=result.usage.total_cost_usd,
            )
            await storage.save_pending_analysis(
                chat_id=user.chat_id,
                telegram_file_id=telegram_file_id,
                telegram_file_unique_id=telegram_file_unique_id,
                caption_text=caption_text,
                correction_text=correction_text,
                analysis=result.analysis,
                analysis_message_id=previous_pending.analysis_message_id if previous_pending else None,
            )
            today_totals = await storage.get_daily_nutrition(
                chat_id=user.chat_id,
                local_date=local_today(settings),
            )
            text = format_analysis_message(
                analysis=result.analysis,
                today_totals=today_totals,
                daily_targets=user.nutrition_targets,
                is_saved=False,
                display_name=user.display_name or user.first_name or "there",
            )
            refreshed_pending = await storage.get_pending_analysis(user.chat_id)
            message_id = await edit_or_send_pending_message(
                chat_id=user.chat_id,
                thread_message=message,
                pending=refreshed_pending,
                text=text,
            )
            if message_id is not None:
                await storage.set_pending_analysis_message_id(user.chat_id, message_id)
        except Exception:
            LOGGER.exception("Meal analysis failed for chat %s", user.chat_id)
            await message.reply_text(
                "I couldn't analyze that meal right now. Please try again in a moment.",
                reply_markup=build_main_keyboard(),
            )
        finally:
            try:
                await status_message.delete()
            except BadRequest:
                LOGGER.info("Status message already gone for chat %s", user.chat_id)

    async def open_settings(message, user: UserProfile) -> None:
        today_total = await storage.get_daily_total(chat_id=user.chat_id, local_date=local_today(settings))
        await message.reply_text(
            format_settings_message(user, today_total),
            parse_mode=ParseMode.HTML,
            reply_markup=build_settings_keyboard(),
        )

    async def show_today(message, user: UserProfile) -> None:
        today = local_today(settings)
        today_totals = await storage.get_daily_nutrition(chat_id=user.chat_id, local_date=today)
        meals = await storage.list_meals_for_day(chat_id=user.chat_id, local_date=today)
        await message.reply_text(
            format_today_message(user, today_totals, meals),
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_keyboard(),
        )

    async def send_shipped_sticker(message) -> None:
        await message.reply_sticker(SHIPPED_STICKER_FILE_ID)
        await message.reply_text(
            (
                "🚀 Nibbler shipped.\n\n"
                "Try sending me a photo of any food or drink, or just describe what you ate, and I'll estimate it.\n"
                "If I miss something, just send a comment and I'll update the estimate 🙂"
            ),
            reply_markup=build_main_keyboard(),
        )

    async def send_post_password_welcome(message) -> None:
        await message.reply_sticker(INTRO_STICKER_FILE_ID)
        await message.reply_text(
            format_post_password_welcome_message(),
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_keyboard(),
        )

    async def send_weekly_chart(message, user: UserProfile) -> None:
        end_date = local_now(settings).date()
        start_date = end_date - timedelta(days=6)
        points = await storage.get_daily_calories_between(
            chat_id=user.chat_id,
            start_date=start_date,
            end_date=end_date,
        )
        chart_bytes = build_weekly_chart(
            points=points,
            daily_limit=user.daily_calorie_limit or settings.default_daily_calorie_limit,
            title="Nibbler weekly chart",
            subtitle=f"{start_date.isoformat()} to {end_date.isoformat()}",
        )
        await message.reply_photo(
            photo=InputFile(chart_bytes, filename="weekly-chart.png"),
            caption=format_weekly_summary_message(
                user=user,
                start_date=start_date,
                end_date=end_date,
                points=points,
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_keyboard(),
        )

    async def send_monthly_chart(message, user: UserProfile) -> None:
        today = local_now(settings).date()
        start_date, end_date = month_to_date_bounds(today)
        previous_month_start, previous_month_end_full = previous_month_bounds(start_date)
        comparable_days = (end_date - start_date).days
        previous_end_date = min(
            previous_month_start + timedelta(days=comparable_days),
            previous_month_end_full,
        )
        points = await storage.get_daily_calories_between(
            chat_id=user.chat_id,
            start_date=start_date,
            end_date=end_date,
        )
        previous_points = await storage.get_daily_calories_between(
            chat_id=user.chat_id,
            start_date=previous_month_start,
            end_date=previous_end_date,
        )
        chart_bytes = build_weekly_chart(
            points=points,
            daily_limit=user.daily_calorie_limit or settings.default_daily_calorie_limit,
            title="Nibbler month-to-date chart",
            subtitle=f"{start_date.isoformat()} to {end_date.isoformat()}",
        )
        await message.reply_photo(
            photo=InputFile(chart_bytes, filename="monthly-chart.png"),
            caption=format_manual_monthly_chart_message(
                user=user,
                start_date=start_date,
                end_date=end_date,
                points=points,
                previous_points=previous_points,
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_keyboard(),
        )

    def local_date_from_utc_iso(utc_iso: str) -> str:
        timestamp = datetime.fromisoformat(utc_iso)
        return timestamp.astimezone(settings.timezone).date().isoformat()

    async def auto_confirm_pending_analyses(context: ContextTypes.DEFAULT_TYPE) -> None:
        pending_items = await storage.list_pending_analyses_ready_for_auto_confirm(
            older_than_minutes=AUTO_CONFIRM_PENDING_MINUTES
        )
        for pending in pending_items:
            user = await storage.get_user(pending.chat_id)
            if user is None or not user.is_ready:
                await storage.clear_pending_analysis(pending.chat_id)
                continue
            local_date = local_date_from_utc_iso(pending.updated_at)
            meal = await storage.confirm_pending_analysis(
                chat_id=pending.chat_id,
                local_date=local_date,
            )
            if meal is None:
                continue
            today_totals = await storage.get_daily_nutrition(
                chat_id=user.chat_id,
                local_date=local_date,
            )
            text = (
                format_analysis_message(
                    analysis=meal.analysis,
                    today_totals=today_totals,
                    daily_targets=user.nutrition_targets,
                    is_saved=True,
                    display_name=user.display_name or user.first_name or "there",
                )
                + f"\n\n⏱️ Auto-saved after {AUTO_CONFIRM_PENDING_MINUTES} minutes."
            )
            try:
                if pending.analysis_message_id is not None:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=pending.chat_id,
                            message_id=pending.analysis_message_id,
                            text=text,
                            parse_mode=ParseMode.HTML,
                        )
                        continue
                    except BadRequest:
                        LOGGER.info(
                            "Could not edit pending message for auto-save in chat %s",
                            pending.chat_id,
                        )
                await context.bot.send_message(
                    chat_id=pending.chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=build_main_keyboard(),
                )
            except Exception:
                LOGGER.exception("Failed to notify chat %s about auto-saved meal", pending.chat_id)

    async def handle_password_text(message, user: UserProfile) -> None:
        now = local_now(settings)
        current_month = month_key(now)
        attempts = user.password_attempts if user.password_attempt_month == current_month else 0
        if attempts >= 3:
            await message.reply_text(
                f"🔒 Access is locked until next month. Current lock window: {describe_blocked_month(now)}."
            )
            return
        if (message.text or "").strip() == settings.access_password:
            await storage.set_authorized(
                chat_id=user.chat_id,
                month_key=current_month,
                default_daily_calorie_limit=settings.default_daily_calorie_limit,
            )
            await storage.set_onboarding_state(user.chat_id, "awaiting_name")
            await send_post_password_welcome(message)
            return
        attempts += 1
        await storage.update_password_attempts(
            chat_id=user.chat_id,
            attempts=attempts,
            month_key=current_month,
            authorized=False,
        )
        if attempts >= 3:
            await message.reply_text(
                (
                    "❌ Wrong password.\n\n"
                    f"That was attempt {attempts}/3, so access is locked for {describe_blocked_month(now)}."
                )
            )
            return
        await message.reply_text(f"❌ Wrong password. Attempt {attempts}/3.")

    async def handle_name_input(message, user: UserProfile) -> None:
        name = (message.text or "").strip()
        if name in {"⚙️ Settings", "📊 Today", "📈 Week", "🗓️ Month"}:
            await message.reply_text("Please send the name you want me to use.")
            return
        if not name:
            await message.reply_text("Please send a non-empty name.")
            return
        await storage.update_display_name(user.chat_id, name)
        if user.onboarding_state == "awaiting_name":
            await storage.set_onboarding_state(user.chat_id, "awaiting_limit")
            await message.reply_text(
                (
                    f"Nice to meet you, {escape(name)} 👋\n\n"
                    "What daily calorie target should I use? Send a whole number like 1800."
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=build_main_keyboard(),
            )
            return
        await storage.set_onboarding_state(user.chat_id, None)
        await message.reply_text(
            f"✏️ Name updated to <b>{escape(name)}</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_keyboard(),
        )

    async def handle_limit_input(message, user: UserProfile) -> None:
        raw = (message.text or "").strip()
        if raw in {"⚙️ Settings", "📊 Today", "📈 Week", "🗓️ Month"}:
            await message.reply_text("Please send a whole number like 1800.")
            return
        try:
            limit = int(raw)
        except ValueError:
            await message.reply_text("Please send a whole number like 1800.")
            return
        if limit < 500 or limit > 10000:
            await message.reply_text("Please choose a realistic daily limit between 500 and 10000 kcal.")
            return
        await storage.update_daily_limit(user.chat_id, limit)
        if user.onboarding_state == "awaiting_limit":
            await storage.set_onboarding_state(user.chat_id, "awaiting_goal")
            await message.reply_text(
                (
                    f"🎯 Daily goal saved: <b>{limit} kcal</b>\n\n"
                    "What are you using Nibbler for?\n"
                    "I’ll calculate starter protein/fat/carbs limits from this. "
                    "You can change macro limits later in Settings."
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=build_nutrition_goal_keyboard(),
            )
            return
        await storage.set_onboarding_state(user.chat_id, None)
        refreshed = await storage.get_user(user.chat_id)
        targets = refreshed.nutrition_targets if refreshed else user.nutrition_targets
        await message.reply_text(
            (
                f"🎯 Daily limit updated to <b>{limit} kcal</b>.\n\n"
                "I recalculated macro limits from your goal:\n"
                f"P {targets.protein_g:.0f} g • F {targets.fat_g:.0f} g • C {targets.carbs_g:.0f} g"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_keyboard(),
        )

    async def handle_macro_limits_input(message, user: UserProfile) -> None:
        raw = (message.text or "").strip()
        values = [int(float(value.replace(",", "."))) for value in re.findall(r"\d+(?:[.,]\d+)?", raw)]
        if len(values) < 3:
            await message.reply_text(
                "Please send three numbers: protein fat carbs. Example: 120 55 180.",
                reply_markup=build_main_keyboard(),
            )
            return
        protein_limit, fat_limit, carbs_limit = values[:3]
        if not (0 <= protein_limit <= 500 and 0 <= fat_limit <= 300 and 0 <= carbs_limit <= 800):
            await message.reply_text(
                "Please choose realistic macro limits. Example: 120 55 180.",
                reply_markup=build_main_keyboard(),
            )
            return
        await storage.update_macro_limits(
            chat_id=user.chat_id,
            protein_limit_g=protein_limit,
            fat_limit_g=fat_limit,
            carbs_limit_g=carbs_limit,
        )
        await storage.set_onboarding_state(user.chat_id, None)
        await message.reply_text(
            (
                "🥩 Macro limits updated.\n\n"
                f"P {protein_limit} g • F {fat_limit} g • C {carbs_limit} g"
            ),
            reply_markup=build_main_keyboard(),
        )

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await ensure_private_chat(update):
            return
        user = await ensure_user(update)
        if user is None or update.effective_message is None:
            return
        await send_welcome_or_password_prompt(update.effective_message, user)

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await ensure_private_chat(update) or update.effective_message is None:
            return
        await ensure_user(update)
        await update.effective_message.reply_text(
            format_help_message(),
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_keyboard(),
        )

    async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = await ensure_ready_user(update)
        if user is None or update.effective_message is None:
            return
        await show_today(update.effective_message, user)

    async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = await ensure_ready_user(update)
        if user is None or update.effective_message is None:
            return
        await open_settings(update.effective_message, user)

    async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = await ensure_admin(update)
        if user is None or update.effective_message is None:
            return
        db_path = Path(settings.database_path)
        current_month_key = local_now(settings).strftime("%Y-%m")
        users_count = await storage.count_users()
        pending_count = await storage.count_pending_analyses()
        total_generations, total_cost = await storage.get_openai_usage_summary()
        monthly_generations, monthly_cost = await storage.get_openai_usage_summary_for_month(
            current_month_key
        )
        db_size = db_path.stat().st_size if db_path.exists() else 0
        await update.effective_message.reply_text(
            (
                "🩺 <b>Nibbler health</b>\n\n"
                f"<b>Status:</b> ok\n"
                f"<b>Bot uptime:</b> {monitoring.app_uptime()}\n"
                f"<b>Model:</b> {escape(settings.openai_model)}\n"
                f"<b>Users:</b> {users_count}\n"
                f"<b>Pending analyses:</b> {pending_count}\n"
                f"<b>Generations total:</b> {total_generations}\n"
                f"<b>Generations this month:</b> {monthly_generations}\n"
                f"<b>Cost total:</b> ${total_cost:.4f}\n"
                f"<b>Cost this month:</b> ${monthly_cost:.4f}\n"
                f"<b>DB size:</b> {round(db_size / 1024, 1)} KB"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_keyboard(),
        )

    async def server_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = await ensure_admin(update)
        if user is None or update.effective_message is None:
            return
        await update.effective_message.reply_text(
            monitoring.server_snapshot(),
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_keyboard(),
        )

    async def containers_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = await ensure_admin(update)
        if user is None or update.effective_message is None:
            return
        try:
            snapshots = await monitoring.list_containers()
            text = monitoring.format_containers(snapshots)
        except Exception:
            LOGGER.exception("Failed to load Docker container stats for admin chat %s", user.chat_id)
            text = "I couldn't read Docker container stats right now."
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_keyboard(),
        )

    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await ensure_private_chat(update):
            return
        message = update.effective_message
        if message is None:
            return
        user = await ensure_user(update)
        if user is None:
            return
        text = (message.text or "").strip()
        if not user.is_authorized:
            await handle_password_text(message, user)
            return
        if user.onboarding_state in {"awaiting_name", "awaiting_name_update"}:
            await handle_name_input(message, user)
            return
        if user.onboarding_state in {"awaiting_limit", "awaiting_limit_update"}:
            await handle_limit_input(message, user)
            return
        if user.onboarding_state == "awaiting_goal":
            await message.reply_text(
                "Please choose one of the goal buttons so I can calculate starter macro limits.",
                reply_markup=build_nutrition_goal_keyboard(),
            )
            return
        if user.onboarding_state == "awaiting_macro_limits_update":
            await handle_macro_limits_input(message, user)
            return
        if text == "⚙️ Settings":
            refreshed = await storage.get_user(user.chat_id)
            if refreshed is not None:
                await open_settings(message, refreshed)
            return
        if text == "📊 Today":
            refreshed = await storage.get_user(user.chat_id)
            if refreshed is not None and refreshed.is_ready:
                await show_today(message, refreshed)
            return
        if text == "📈 Week":
            refreshed = await storage.get_user(user.chat_id)
            if refreshed is not None and refreshed.is_ready:
                await send_weekly_chart(message, refreshed)
            return
        if text == "🗓️ Month":
            refreshed = await storage.get_user(user.chat_id)
            if refreshed is not None and refreshed.is_ready:
                await send_monthly_chart(message, refreshed)
            return
        if not user.is_ready:
            await send_welcome_or_password_prompt(message, user)
            return
        pending = await storage.get_pending_analysis(user.chat_id)
        if pending is not None:
            await analyze_meal_input(
                message=message,
                user=user,
                telegram_file_id=pending.telegram_file_id,
                telegram_file_unique_id=pending.telegram_file_unique_id,
                caption_text=pending.caption_text,
                correction_text=text,
                previous_pending=pending,
            )
            return
        await analyze_meal_input(
            message=message,
            user=user,
            telegram_file_id="",
            telegram_file_unique_id="",
            caption_text=text,
            correction_text="",
            previous_pending=None,
        )

    async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = await ensure_ready_user(update)
        if user is None:
            return
        message = update.effective_message
        if message is None or not message.photo:
            return
        if message.media_group_id:
            cutoff = seen_media_groups.get(message.media_group_id)
            now = datetime.utcnow()
            if cutoff is None or cutoff < now:
                seen_media_groups[message.media_group_id] = now + timedelta(minutes=5)
                await message.reply_text(
                    "Please send one photo at a time so I can estimate it properly.",
                    reply_markup=build_main_keyboard(),
                )
            return
        largest_photo = message.photo[-1]
        pending = await storage.get_pending_analysis(user.chat_id)
        await analyze_meal_input(
            message=message,
            user=user,
            telegram_file_id=largest_photo.file_id,
            telegram_file_unique_id=largest_photo.file_unique_id,
            caption_text=message.caption or "",
            correction_text="",
            previous_pending=pending,
        )

    async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        if not await ensure_private_chat(update):
            return
        user = await ensure_user(update)
        if user is None:
            await query.answer()
            return
        data = query.data or ""
        if not user.is_authorized:
            await query.answer("Please unlock the bot first.", show_alert=True)
            return
        if not user.is_ready and data not in {"settings:name", "settings:limit"} and not data.startswith("goal:"):
            await query.answer("Finish setup first.", show_alert=True)
            return
        if data.startswith("goal:"):
            goal = normalize_nutrition_goal(data.split(":", 1)[1])
            await query.answer()
            targets = await storage.update_nutrition_goal(user.chat_id, goal)
            await storage.set_onboarding_state(user.chat_id, None)
            goal_label = NUTRITION_GOALS[goal][0]
            await query.edit_message_text(
                (
                    f"🥩 Macro limits set for <b>{escape(goal_label)}</b>.\n\n"
                    f"P {targets.protein_g:.0f} g • F {targets.fat_g:.0f} g • C {targets.carbs_g:.0f} g\n\n"
                    "You can change these later in ⚙️ Settings."
                ),
                parse_mode=ParseMode.HTML,
            )
            await send_shipped_sticker(query.message)
            return
        if data == "meal:fix_hint":
            await query.answer(
                (
                    "💬 Send any comment you want and I'll use it in the next estimate.\n\n"
                    "Examples:\n"
                    "• there was also a piece of processed cheese on the plate\n"
                    "• I also drank a glass of orange juice\n"
                    "• it was Coke Zero 🙂"
                ),
                show_alert=True,
            )
            return

        if data == "meal:discard":
            pending = await storage.get_pending_analysis(user.chat_id)
            if pending is None:
                await query.answer("This estimate is no longer pending.", show_alert=True)
                return
            await query.answer()
            await storage.clear_pending_analysis(user.chat_id)
            text = format_analysis_message(
                analysis=pending.analysis,
                today_totals=await storage.get_daily_nutrition(
                    chat_id=user.chat_id,
                    local_date=local_today(settings),
                ),
                daily_targets=user.nutrition_targets,
                is_saved=False,
                display_name=user.display_name or user.first_name or "there",
            )
            text = f"{text}\n\n<i>Discarded.</i>"
            await query.edit_message_text(text=text, parse_mode=ParseMode.HTML)
            return

        if data == "meal:save":
            meal = await storage.confirm_pending_analysis(
                chat_id=user.chat_id,
                local_date=local_today(settings),
            )
            if meal is None:
                await query.answer("Nothing to save.", show_alert=True)
                return
            await query.answer()
            today_totals = await storage.get_daily_nutrition(
                chat_id=user.chat_id,
                local_date=local_today(settings),
            )
            await query.edit_message_text(
                text=format_analysis_message(
                    analysis=meal.analysis,
                    today_totals=today_totals,
                    daily_targets=user.nutrition_targets,
                    is_saved=True,
                    display_name=user.display_name or user.first_name or "there",
                ),
                parse_mode=ParseMode.HTML,
            )
            return

        if data == "settings:open":
            await query.answer()
            today_total = await storage.get_daily_total(chat_id=user.chat_id, local_date=local_today(settings))
            await query.edit_message_text(
                text=format_settings_message(user, today_total),
                parse_mode=ParseMode.HTML,
                reply_markup=build_settings_keyboard(),
            )
            return

        if data == "settings:close":
            await query.answer()
            await query.edit_message_text("Settings closed.")
            return

        if data == "settings:name":
            await query.answer()
            await storage.set_onboarding_state(user.chat_id, "awaiting_name_update")
            await query.message.reply_text(
                "Send the new name you want me to use.",
                reply_markup=build_main_keyboard(),
            )
            return

        if data == "settings:limit":
            await query.answer()
            await storage.set_onboarding_state(user.chat_id, "awaiting_limit_update")
            await query.message.reply_text(
                "Send the new daily calorie limit as a whole number.",
                reply_markup=build_main_keyboard(),
            )
            return

        if data == "settings:macros":
            await query.answer()
            await storage.set_onboarding_state(user.chat_id, "awaiting_macro_limits_update")
            targets = user.nutrition_targets
            await query.message.reply_text(
                (
                    "Send new macro limits as three numbers: protein fat carbs.\n\n"
                    f"Current: P {targets.protein_g:.0f} g • F {targets.fat_g:.0f} g • C {targets.carbs_g:.0f} g\n"
                    "Example: 120 55 180"
                ),
                reply_markup=build_main_keyboard(),
            )
            return

        if data == "settings:today":
            await query.answer()
            today_totals = await storage.get_daily_nutrition(
                chat_id=user.chat_id,
                local_date=local_today(settings),
            )
            meals = await storage.list_meals_for_day(chat_id=user.chat_id, local_date=local_today(settings))
            await query.edit_message_text(
                text=format_today_message(user, today_totals, meals),
                parse_mode=ParseMode.HTML,
            )
            return

        if data == "settings:week":
            await query.answer()
            await send_weekly_chart(query.message, user)
            return

        if data == "settings:month":
            await query.answer()
            await send_monthly_chart(query.message, user)
            return

        if data == "settings:delete":
            await query.answer()
            meals = await storage.list_meals_for_day(chat_id=user.chat_id, local_date=local_today(settings))
            if not meals:
                await query.edit_message_text(
                    text="🗑️ No saved meals to delete today.",
                    reply_markup=build_settings_keyboard(),
                )
                return
            await query.edit_message_text(
                text="Choose a saved meal to delete:",
                reply_markup=build_delete_meal_keyboard(meals),
            )
            return

        if data == "settings:wipe":
            await query.answer()
            await query.edit_message_text(
                text=format_delete_all_data_confirmation_message(),
                parse_mode=ParseMode.HTML,
                reply_markup=build_delete_all_data_keyboard(),
            )
            return

        if data == "settings:wipe:confirm":
            await query.answer()
            deleted = await storage.delete_user_data(user.chat_id)
            if not deleted:
                await query.edit_message_text(
                    text="Your data is already gone. Send /start if you want to begin again.",
                )
                return
            await query.edit_message_text(
                text=(
                    "🧹 <b>All your Nibbler data was deleted.</b>\n\n"
                    "Your profile, saved meals, pending estimate, and personal usage history are gone.\n"
                    "Send <b>/start</b> if you want to begin again."
                ),
                parse_mode=ParseMode.HTML,
            )
            return

        if data.startswith("settings:delete:"):
            meal_id = int(data.split(":")[-1])
            deleted = await storage.delete_meal(chat_id=user.chat_id, meal_id=meal_id)
            if deleted is None:
                await query.answer("That meal no longer exists.", show_alert=True)
                return
            await query.answer()
            today_totals = await storage.get_daily_nutrition(
                chat_id=user.chat_id,
                local_date=local_today(settings),
            )
            await query.edit_message_text(
                text=format_meal_deleted_message(
                    meal=deleted,
                    today_totals=today_totals,
                    daily_targets=user.nutrition_targets,
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=build_settings_keyboard(),
            )
            return

        await query.answer()

    async def send_weekly_summaries(context: ContextTypes.DEFAULT_TYPE) -> None:
        now = local_now(settings)
        if now.weekday() != 0:
            return
        await storage.cleanup_old_pending_analyses()
        end_date = now.date() - timedelta(days=1)
        start_date = end_date - timedelta(days=6)
        period_key = f"{start_date.isoformat()}_{end_date.isoformat()}"
        users = [user for user in await storage.list_authorized_users() if user.is_ready]
        for user in users:
            if await storage.has_report_delivery(
                chat_id=user.chat_id,
                report_kind="weekly",
                report_period=period_key,
            ):
                continue
            points = await storage.get_daily_calories_between(
                chat_id=user.chat_id,
                start_date=start_date,
                end_date=end_date,
            )
            chart_bytes = build_weekly_chart(
                points=points,
                daily_limit=user.daily_calorie_limit or settings.default_daily_calorie_limit,
                title="Nibbler weekly calories",
                subtitle=f"{start_date.isoformat()} to {end_date.isoformat()}",
            )
            await context.bot.send_photo(
                chat_id=user.chat_id,
                photo=InputFile(chart_bytes, filename="weekly-summary.png"),
                caption=format_weekly_summary_message(
                    user=user,
                    start_date=start_date,
                    end_date=end_date,
                    points=points,
                ),
                parse_mode=ParseMode.HTML,
            )
            await storage.mark_report_delivery(
                chat_id=user.chat_id,
                report_kind="weekly",
                report_period=period_key,
            )

    async def send_monthly_summaries(context: ContextTypes.DEFAULT_TYPE) -> None:
        now = local_now(settings)
        if now.day != 1:
            return
        current_month_start, _ = current_month_bounds(now.date())
        period_start, period_end = previous_month_bounds(current_month_start)
        previous_start, previous_end = previous_month_bounds(period_start)
        period_key = period_start.strftime("%Y-%m")
        users = [user for user in await storage.list_authorized_users() if user.is_ready]
        for user in users:
            if await storage.has_report_delivery(
                chat_id=user.chat_id,
                report_kind="monthly",
                report_period=period_key,
            ):
                continue
            points = await storage.get_daily_calories_between(
                chat_id=user.chat_id,
                start_date=period_start,
                end_date=period_end,
            )
            previous_points = await storage.get_daily_calories_between(
                chat_id=user.chat_id,
                start_date=previous_start,
                end_date=previous_end,
            )
            await context.bot.send_message(
                chat_id=user.chat_id,
                text=format_monthly_summary_message(
                    user=user,
                    month_label=period_start.strftime("%B %Y"),
                    points=points,
                    previous_points=previous_points,
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=build_main_keyboard(),
            )
            await storage.mark_report_delivery(
                chat_id=user.chat_id,
                report_kind="monthly",
                report_period=period_key,
            )

    async def post_init(app: Application) -> None:
        await storage.initialize()
        await app.bot.set_my_commands(build_bot_commands())
        for chat_id in settings.admin_chat_ids:
            await app.bot.set_my_commands(
                build_admin_bot_commands(),
                scope=BotCommandScopeChat(chat_id=chat_id),
            )
        app.job_queue.run_daily(
            send_weekly_summaries,
            time=time(
                hour=settings.weekly_summary_hour,
                minute=settings.weekly_summary_minute,
                tzinfo=settings.timezone,
            ),
            name="weekly-summary",
        )
        app.job_queue.run_daily(
            send_monthly_summaries,
            time=time(
                hour=settings.monthly_summary_hour,
                minute=settings.monthly_summary_minute,
                tzinfo=settings.timezone,
            ),
            name="monthly-summary",
        )
        app.job_queue.run_repeating(
            auto_confirm_pending_analyses,
            interval=60,
            first=60,
            name="auto-confirm-pending-meals",
        )

    application.post_init = post_init
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("health", health_command))
    application.add_handler(CommandHandler("server", server_command))
    application.add_handler(CommandHandler("containers", containers_command))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
