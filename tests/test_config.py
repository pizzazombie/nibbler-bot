from __future__ import annotations

from nibbler_bot.config import _optional_int_set, load_settings


def test_optional_int_set_parses_admin_chat_ids(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_CHAT_IDS", "2485222, 12345")

    assert _optional_int_set("ADMIN_CHAT_IDS") == frozenset({2485222, 12345})


def test_load_settings_defaults_to_mini_fallback(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("ACCESS_PASSWORD", "secret")

    settings = load_settings()

    assert settings.openai_model == "gpt-5.4-mini"
    assert settings.openai_reasoning_effort == "low"
    assert settings.openai_request_timeout_seconds == 60
