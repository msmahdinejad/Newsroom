"""Telegram owner-command behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from newsroom.control import ControlSnapshot
from newsroom.delivery import bot as bot_module
from newsroom.delivery.bot import TelegramBot


@pytest.mark.asyncio
async def test_collect_command_uses_configured_cycle_bounds() -> None:
    bot = object.__new__(TelegramBot)
    bot._send_text = AsyncMock()
    db = MagicMock()
    db_context = MagicMock()
    db_context.__enter__.return_value = db
    collect = AsyncMock(
        return_value={"new_items": 3, "sources": 11, "failed": []}
    )
    local_settings = SimpleNamespace(
        collect_limit_per_source=7,
        collect_max_sources_per_cycle=11,
        collect_source_spacing_seconds=0.5,
    )

    with (
        patch.object(bot_module, "get_db", return_value=db_context),
        patch.object(bot_module, "settings", local_settings),
        patch("newsroom.pipeline.collect.collect_sources", collect),
    ):
        result = await bot._handle_collect(123)

    assert result == "ok"
    collect.assert_awaited_once_with(
        db,
        limit_per_source=7,
        max_sources=11,
        source_spacing_seconds=0.5,
    )


@pytest.mark.asyncio
async def test_report_command_enforces_cross_update_cooldown() -> None:
    bot = object.__new__(TelegramBot)
    bot._send_text = AsyncMock()
    query = MagicMock()
    query.filter_by.return_value.first.return_value = None
    query.filter.return_value.order_by.return_value.first.return_value = (
        SimpleNamespace()
    )
    db = MagicMock()
    db.query.return_value = query
    db_context = MagicMock()
    db_context.__enter__.return_value = db
    local_settings = SimpleNamespace(manual_cooldown_seconds=600)

    with (
        patch.object(bot_module, "get_db", return_value=db_context),
        patch.object(bot_module, "settings", local_settings),
    ):
        result = await bot._handle_report(
            chat_id=123,
            mode="manual",
            user_id=456,
            update_id=1002,
        )

    assert result == "busy"
    db.add.assert_not_called()
    bot._send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_menu_uses_selected_language() -> None:
    bot = object.__new__(TelegramBot)
    bot.api = AsyncMock()
    bot._control_snapshot = MagicMock(
        return_value=ControlSnapshot(
            report_language="en",
            report_source_types=("telegram",),
            report_story_count=20,
            schedule_times=("01:15", "13:45"),
            schedule_enabled=True,
        )
    )

    await bot._send_menu(123)

    payload = bot.api.send_message.await_args
    assert "Welcome to Newsroom" in payload.args[1]
    assert "stories=20" in payload.args[1]
    assert payload.kwargs["reply_markup"]["inline_keyboard"][0][0]["text"] == "Report now"
