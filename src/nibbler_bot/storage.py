from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from .models import DailyCalories, MealAnalysis, MealEntry, NutritionTotals, PendingAnalysis, UserProfile


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, database_path: str) -> None:
        self._database_path = Path(database_path)

    async def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._database_path) as db:
            await db.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    display_name TEXT,
                    daily_calorie_limit INTEGER,
                    is_authorized INTEGER NOT NULL DEFAULT 0,
                    password_attempts INTEGER NOT NULL DEFAULT 0,
                    password_attempt_month TEXT,
                    onboarding_state TEXT,
                    state_payload TEXT NOT NULL DEFAULT '{}',
                    last_seen_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pending_analyses (
                    chat_id INTEGER PRIMARY KEY,
                    telegram_file_id TEXT NOT NULL,
                    telegram_file_unique_id TEXT NOT NULL,
                    caption_text TEXT NOT NULL DEFAULT '',
                    correction_text TEXT NOT NULL DEFAULT '',
                    analysis_json TEXT NOT NULL,
                    total_calories INTEGER NOT NULL,
                    analysis_message_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS meal_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    local_date TEXT NOT NULL,
                    source_file_unique_id TEXT,
                    caption_text TEXT NOT NULL DEFAULT '',
                    correction_text TEXT NOT NULL DEFAULT '',
                    analysis_json TEXT NOT NULL,
                    total_calories INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS openai_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    local_date TEXT NOT NULL,
                    request_kind TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_cost_usd REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS report_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    report_kind TEXT NOT NULL,
                    report_period TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(chat_id, report_kind, report_period)
                );
                """
            )
            await db.commit()

    async def upsert_user_identity(
        self,
        *,
        chat_id: int,
        username: str | None,
        first_name: str | None,
    ) -> None:
        now = _utc_now_iso()
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                """
                INSERT INTO users (
                    chat_id,
                    username,
                    first_name,
                    last_seen_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                """,
                (chat_id, username, first_name, now, now, now),
            )
            await db.commit()

    async def get_user(self, chat_id: int) -> UserProfile | None:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
            row = await cursor.fetchone()
        if row is None:
            return None
        return UserProfile(
            chat_id=row["chat_id"],
            username=row["username"],
            first_name=row["first_name"],
            display_name=row["display_name"],
            daily_calorie_limit=row["daily_calorie_limit"],
            is_authorized=bool(row["is_authorized"]),
            password_attempts=row["password_attempts"],
            password_attempt_month=row["password_attempt_month"],
            onboarding_state=row["onboarding_state"],
            state_payload=json.loads(row["state_payload"] or "{}"),
        )

    async def update_password_attempts(
        self,
        *,
        chat_id: int,
        attempts: int,
        month_key: str,
        authorized: bool = False,
    ) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                """
                UPDATE users
                SET password_attempts = ?,
                    password_attempt_month = ?,
                    is_authorized = ?,
                    updated_at = ?
                WHERE chat_id = ?
                """,
                (attempts, month_key, 1 if authorized else 0, _utc_now_iso(), chat_id),
            )
            await db.commit()

    async def set_authorized(
        self,
        *,
        chat_id: int,
        month_key: str,
        default_daily_calorie_limit: int,
    ) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                """
                UPDATE users
                SET is_authorized = 1,
                    password_attempts = 0,
                    password_attempt_month = ?,
                    onboarding_state = COALESCE(onboarding_state, 'awaiting_name'),
                    daily_calorie_limit = COALESCE(daily_calorie_limit, ?),
                    updated_at = ?
                WHERE chat_id = ?
                """,
                (month_key, default_daily_calorie_limit, _utc_now_iso(), chat_id),
            )
            await db.commit()

    async def set_onboarding_state(
        self,
        chat_id: int,
        state: str | None,
        payload: dict[str, object] | None = None,
    ) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                """
                UPDATE users
                SET onboarding_state = ?,
                    state_payload = ?,
                    updated_at = ?
                WHERE chat_id = ?
                """,
                (state, json.dumps(payload or {}), _utc_now_iso(), chat_id),
            )
            await db.commit()

    async def update_display_name(self, chat_id: int, display_name: str) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                """
                UPDATE users
                SET display_name = ?, updated_at = ?
                WHERE chat_id = ?
                """,
                (display_name, _utc_now_iso(), chat_id),
            )
            await db.commit()

    async def update_daily_limit(self, chat_id: int, daily_calorie_limit: int) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                """
                UPDATE users
                SET daily_calorie_limit = ?, updated_at = ?
                WHERE chat_id = ?
                """,
                (daily_calorie_limit, _utc_now_iso(), chat_id),
            )
            await db.commit()

    async def save_pending_analysis(
        self,
        *,
        chat_id: int,
        telegram_file_id: str,
        telegram_file_unique_id: str,
        caption_text: str,
        correction_text: str,
        analysis: MealAnalysis,
        analysis_message_id: int | None = None,
    ) -> None:
        now = _utc_now_iso()
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                """
                INSERT INTO pending_analyses (
                    chat_id,
                    telegram_file_id,
                    telegram_file_unique_id,
                    caption_text,
                    correction_text,
                    analysis_json,
                    total_calories,
                    analysis_message_id,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    telegram_file_id = excluded.telegram_file_id,
                    telegram_file_unique_id = excluded.telegram_file_unique_id,
                    caption_text = excluded.caption_text,
                    correction_text = excluded.correction_text,
                    analysis_json = excluded.analysis_json,
                    total_calories = excluded.total_calories,
                    analysis_message_id = COALESCE(excluded.analysis_message_id, pending_analyses.analysis_message_id),
                    updated_at = excluded.updated_at
                """,
                (
                    chat_id,
                    telegram_file_id,
                    telegram_file_unique_id,
                    caption_text,
                    correction_text,
                    json.dumps(analysis.to_dict()),
                    analysis.total_calories,
                    analysis_message_id,
                    now,
                    now,
                ),
            )
            await db.commit()

    async def set_pending_analysis_message_id(self, chat_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                """
                UPDATE pending_analyses
                SET analysis_message_id = ?, updated_at = ?
                WHERE chat_id = ?
                """,
                (message_id, _utc_now_iso(), chat_id),
            )
            await db.commit()

    async def get_pending_analysis(self, chat_id: int) -> PendingAnalysis | None:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM pending_analyses WHERE chat_id = ?",
                (chat_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return PendingAnalysis(
            chat_id=row["chat_id"],
            telegram_file_id=row["telegram_file_id"],
            telegram_file_unique_id=row["telegram_file_unique_id"],
            caption_text=row["caption_text"],
            correction_text=row["correction_text"],
            analysis=MealAnalysis.from_dict(json.loads(row["analysis_json"])),
            analysis_message_id=row["analysis_message_id"],
            updated_at=row["updated_at"],
        )

    async def clear_pending_analysis(self, chat_id: int) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute("DELETE FROM pending_analyses WHERE chat_id = ?", (chat_id,))
            await db.commit()

    async def list_pending_analyses_ready_for_auto_confirm(
        self,
        *,
        older_than_minutes: int,
    ) -> list[PendingAnalysis]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT *
                FROM pending_analyses
                WHERE updated_at < ?
                ORDER BY updated_at ASC
                """,
                (cutoff.isoformat(),),
            )
            rows = await cursor.fetchall()
        return [
            PendingAnalysis(
                chat_id=row["chat_id"],
                telegram_file_id=row["telegram_file_id"],
                telegram_file_unique_id=row["telegram_file_unique_id"],
                caption_text=row["caption_text"],
                correction_text=row["correction_text"],
                analysis=MealAnalysis.from_dict(json.loads(row["analysis_json"])),
                analysis_message_id=row["analysis_message_id"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def confirm_pending_analysis(self, *, chat_id: int, local_date: str) -> MealEntry | None:
        pending = await self.get_pending_analysis(chat_id)
        if pending is None:
            return None
        created_at = _utc_now_iso()
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO meal_entries (
                    chat_id,
                    local_date,
                    source_file_unique_id,
                    caption_text,
                    correction_text,
                    analysis_json,
                    total_calories,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    local_date,
                    pending.telegram_file_unique_id,
                    pending.caption_text,
                    pending.correction_text,
                    json.dumps(pending.analysis.to_dict()),
                    pending.analysis.total_calories,
                    created_at,
                ),
            )
            await db.execute("DELETE FROM pending_analyses WHERE chat_id = ?", (chat_id,))
            await db.commit()
            meal_id = cursor.lastrowid
        return MealEntry(
            id=int(meal_id),
            chat_id=chat_id,
            local_date=local_date,
            total_calories=pending.analysis.total_calories,
            analysis=pending.analysis,
            created_at=created_at,
        )

    async def list_meals_for_day(self, *, chat_id: int, local_date: str) -> list[MealEntry]:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT *
                FROM meal_entries
                WHERE chat_id = ? AND local_date = ?
                ORDER BY id DESC
                """,
                (chat_id, local_date),
            )
            rows = await cursor.fetchall()
        return [
            MealEntry(
                id=row["id"],
                chat_id=row["chat_id"],
                local_date=row["local_date"],
                total_calories=row["total_calories"],
                analysis=MealAnalysis.from_dict(json.loads(row["analysis_json"])),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def delete_meal(self, *, chat_id: int, meal_id: int) -> MealEntry | None:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM meal_entries WHERE chat_id = ? AND id = ?",
                (chat_id, meal_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            await db.execute("DELETE FROM meal_entries WHERE chat_id = ? AND id = ?", (chat_id, meal_id))
            await db.commit()
        return MealEntry(
            id=row["id"],
            chat_id=row["chat_id"],
            local_date=row["local_date"],
            total_calories=row["total_calories"],
            analysis=MealAnalysis.from_dict(json.loads(row["analysis_json"])),
            created_at=row["created_at"],
        )

    async def delete_user_data(self, chat_id: int) -> bool:
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute("SELECT 1 FROM users WHERE chat_id = ?", (chat_id,))
            exists = await cursor.fetchone()
            if exists is None:
                return False
            await db.execute("DELETE FROM pending_analyses WHERE chat_id = ?", (chat_id,))
            await db.execute("DELETE FROM meal_entries WHERE chat_id = ?", (chat_id,))
            await db.execute("DELETE FROM openai_requests WHERE chat_id = ?", (chat_id,))
            await db.execute("DELETE FROM report_deliveries WHERE chat_id = ?", (chat_id,))
            await db.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
            await db.commit()
        return True

    async def get_daily_total(self, *, chat_id: int, local_date: str) -> int:
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute(
                """
                SELECT COALESCE(SUM(total_calories), 0)
                FROM meal_entries
                WHERE chat_id = ? AND local_date = ?
                """,
                (chat_id, local_date),
            )
            row = await cursor.fetchone()
        return int(row[0] or 0)

    async def get_daily_nutrition(self, *, chat_id: int, local_date: str) -> NutritionTotals:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT total_calories, analysis_json
                FROM meal_entries
                WHERE chat_id = ? AND local_date = ?
                """,
                (chat_id, local_date),
            )
            rows = await cursor.fetchall()
        totals = NutritionTotals()
        for row in rows:
            analysis = MealAnalysis.from_dict(json.loads(row["analysis_json"]))
            totals = totals.add(
                NutritionTotals(
                    calories=int(row["total_calories"] or 0),
                    protein_g=analysis.total_protein_g,
                    fat_g=analysis.total_fat_g,
                    carbs_g=analysis.total_carbs_g,
                )
            )
        return totals

    async def record_openai_usage(
        self,
        *,
        chat_id: int,
        local_date: str,
        request_kind: str,
        model: str,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        total_cost_usd: float,
    ) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                """
                INSERT INTO openai_requests (
                    chat_id,
                    local_date,
                    request_kind,
                    model,
                    input_tokens,
                    cached_input_tokens,
                    output_tokens,
                    total_cost_usd,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    local_date,
                    request_kind,
                    model,
                    input_tokens,
                    cached_input_tokens,
                    output_tokens,
                    total_cost_usd,
                    _utc_now_iso(),
                ),
            )
            await db.commit()

    async def count_generations_for_day(self, *, chat_id: int, local_date: str) -> int:
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM openai_requests
                WHERE chat_id = ? AND local_date = ?
                """,
                (chat_id, local_date),
            )
            row = await cursor.fetchone()
        return int(row[0] or 0)

    async def get_openai_usage_summary(self) -> tuple[int, float]:
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(total_cost_usd), 0)
                FROM openai_requests
                """
            )
            row = await cursor.fetchone()
        return int(row[0] or 0), float(row[1] or 0)

    async def get_openai_usage_summary_for_month(self, month_key: str) -> tuple[int, float]:
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(total_cost_usd), 0)
                FROM openai_requests
                WHERE local_date LIKE ?
                """,
                (f"{month_key}-%",),
            )
            row = await cursor.fetchone()
        return int(row[0] or 0), float(row[1] or 0)

    async def list_authorized_users(self) -> list[UserProfile]:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT *
                FROM users
                WHERE is_authorized = 1
                ORDER BY chat_id ASC
                """
            )
            rows = await cursor.fetchall()
        return [
            UserProfile(
                chat_id=row["chat_id"],
                username=row["username"],
                first_name=row["first_name"],
                display_name=row["display_name"],
                daily_calorie_limit=row["daily_calorie_limit"],
                is_authorized=bool(row["is_authorized"]),
                password_attempts=row["password_attempts"],
                password_attempt_month=row["password_attempt_month"],
                onboarding_state=row["onboarding_state"],
                state_payload=json.loads(row["state_payload"] or "{}"),
            )
            for row in rows
        ]

    async def count_users(self) -> int:
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM users")
            row = await cursor.fetchone()
        return int(row[0] or 0)

    async def count_pending_analyses(self) -> int:
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM pending_analyses")
            row = await cursor.fetchone()
        return int(row[0] or 0)

    async def get_daily_calories_between(
        self,
        *,
        chat_id: int,
        start_date: date,
        end_date: date,
    ) -> list[DailyCalories]:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT local_date, COALESCE(SUM(total_calories), 0) AS calories
                FROM meal_entries
                WHERE chat_id = ?
                  AND local_date >= ?
                  AND local_date <= ?
                GROUP BY local_date
                ORDER BY local_date ASC
                """,
                (chat_id, start_date.isoformat(), end_date.isoformat()),
            )
            rows = await cursor.fetchall()
        values = {row["local_date"]: int(row["calories"] or 0) for row in rows}
        result: list[DailyCalories] = []
        cursor_date = start_date
        while cursor_date <= end_date:
            iso_value = cursor_date.isoformat()
            result.append(DailyCalories(local_date=iso_value, calories=values.get(iso_value, 0)))
            cursor_date += timedelta(days=1)
        return result

    async def has_report_delivery(
        self,
        *,
        chat_id: int,
        report_kind: str,
        report_period: str,
    ) -> bool:
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute(
                """
                SELECT 1
                FROM report_deliveries
                WHERE chat_id = ? AND report_kind = ? AND report_period = ?
                LIMIT 1
                """,
                (chat_id, report_kind, report_period),
            )
            row = await cursor.fetchone()
        return row is not None

    async def mark_report_delivery(
        self,
        *,
        chat_id: int,
        report_kind: str,
        report_period: str,
    ) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO report_deliveries (
                    chat_id,
                    report_kind,
                    report_period,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, report_kind, report_period, _utc_now_iso()),
            )
            await db.commit()

    async def cleanup_old_pending_analyses(self, *, max_age_days: int = 3) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                """
                DELETE FROM pending_analyses
                WHERE updated_at < ?
                """,
                (cutoff.isoformat(),),
            )
            await db.commit()
