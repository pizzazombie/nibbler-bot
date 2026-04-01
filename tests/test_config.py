from __future__ import annotations

from nibbler_bot.config import _optional_int_set


def test_optional_int_set_parses_admin_chat_ids(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_CHAT_IDS", "2485222, 12345")

    assert _optional_int_set("ADMIN_CHAT_IDS") == frozenset({2485222, 12345})
