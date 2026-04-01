from __future__ import annotations

import logging
from datetime import datetime, timezone

from telegram.ext import ApplicationBuilder

from .bot import register_handlers
from .config import load_settings
from .meal_analyzer import MealAnalyzer
from .monitoring import MonitoringService
from .storage import Storage


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> None:
    configure_logging()
    settings = load_settings()
    storage = Storage(settings.database_path)
    analyzer = MealAnalyzer(settings)
    monitoring = MonitoringService(started_at=datetime.now(timezone.utc))
    application = ApplicationBuilder().token(settings.telegram_bot_token).build()
    register_handlers(
        application,
        settings=settings,
        storage=storage,
        analyzer=analyzer,
        monitoring=monitoring,
    )
    application.run_polling(allowed_updates=["message", "callback_query", "my_chat_member"])
