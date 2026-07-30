"""Command handler tests — dispatch routing, /latest, /help, access check."""

from unittest.mock import AsyncMock

import pytest

from newsroom.delivery.bot import HELP_TEXT, MENU_KEYBOARD, TelegramBot


def make_bot():
    """Create a bot with mocked API client."""
    bot = TelegramBot.__new__(TelegramBot)
    bot.api = AsyncMock()
    bot._offset = 0
    bot._last_update_ts = None
    bot._last_delivery_ts = None
    bot._bot_info = None
    bot._polling_alive = False
    return bot


def test_menu_keyboard_has_persian_labels():
    """Inline keyboard must contain all 5 Persian labels."""
    labels = [btn["text"] for row in MENU_KEYBOARD["inline_keyboard"] for btn in row]
    assert "\u06af\u0632\u0627\u0631\u0634 \u0641\u0648\u0631\u06cc" in labels
    assert "\u062e\u0628\u0631\u0647\u0627\u06cc \u062c\u062f\u06cc\u062f" in labels
    assert (
        "\u06af\u0632\u0627\u0631\u0634 \u062c\u0627\u0645\u0639 \u0641\u0639\u0644\u06cc" in labels
    )
    assert "\u0622\u062e\u0631\u06cc\u0646 \u06af\u0632\u0627\u0631\u0634" in labels
    assert (
        "\u0631\u0627\u0647\u0646\u0645\u0627\u06cc \u06af\u0632\u0627\u0631\u0634‌\u0647\u0627"
        in labels
    )


def test_menu_keyboard_callback_data():
    """Each Persian button maps to correct callback_data."""
    callbacks = [btn["callback_data"] for row in MENU_KEYBOARD["inline_keyboard"] for btn in row]
    assert "report_now" in callbacks
    assert "report_new" in callbacks
    assert "report_comprehensive" in callbacks
    assert "report_telegram" in callbacks
    assert "report_x" in callbacks
    assert "report_web" in callbacks
    assert "report_github" in callbacks
    assert "report_reddit" in callbacks
    assert "latest" in callbacks
    assert "help" in callbacks


def test_help_text_is_persian():
    assert "\u06af\u0632\u0627\u0631\u0634" in HELP_TEXT
    assert "\u0645\u0648\u0636\u0648\u0639" in HELP_TEXT
    assert "/settings timezone" in HELP_TEXT


def test_help_text_no_secrets():
    assert "token" not in HELP_TEXT.lower()
    assert "password" not in HELP_TEXT.lower()
    assert "api_key" not in HELP_TEXT.lower()


@pytest.mark.asyncio
async def test_dispatch_help():
    bot = make_bot()
    bot._send_menu = AsyncMock()
    result = await bot._dispatch_command(123, "/help", 999, 1, "message")
    assert result == "ok"
    bot._send_menu.assert_called_once_with(123)


@pytest.mark.asyncio
async def test_dispatch_start():
    bot = make_bot()
    bot._send_menu = AsyncMock()
    result = await bot._dispatch_command(123, "/start", 999, 1, "message")
    assert result == "ok"


@pytest.mark.asyncio
async def test_dispatch_latest():
    bot = make_bot()
    bot._handle_latest = AsyncMock(return_value="ok")
    result = await bot._dispatch_command(123, "/latest", 999, 1, "message")
    assert result == "ok"
    bot._handle_latest.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_callback_help():
    bot = make_bot()
    bot._send_menu = AsyncMock()
    result = await bot._dispatch_command(123, "help", 999, 1, "callback")
    assert result == "ok"


@pytest.mark.asyncio
async def test_dispatch_callback_latest():
    bot = make_bot()
    bot._handle_latest = AsyncMock(return_value="ok")
    result = await bot._dispatch_command(123, "latest", 999, 1, "callback")
    assert result == "ok"


@pytest.mark.asyncio
async def test_dispatch_report_now():
    bot = make_bot()
    bot._handle_report = AsyncMock(return_value="ok")
    bot._send_text = AsyncMock()
    result = await bot._dispatch_command(123, "report_now", 999, 1, "callback")
    assert result == "ok"
    bot._handle_report.assert_called_once_with(123, "manual", 999, 1)


@pytest.mark.asyncio
async def test_dispatch_report_new():
    bot = make_bot()
    bot._handle_report = AsyncMock(return_value="ok")
    bot._send_text = AsyncMock()
    result = await bot._dispatch_command(123, "report_new", 999, 1, "callback")
    assert result == "ok"
    bot._handle_report.assert_called_once_with(123, "manual_new", 999, 1)


@pytest.mark.asyncio
async def test_dispatch_report_comprehensive():
    bot = make_bot()
    bot._handle_report = AsyncMock(return_value="ok")
    bot._send_text = AsyncMock()
    result = await bot._dispatch_command(123, "report_comprehensive", 999, 1, "callback")
    assert result == "ok"
    bot._handle_report.assert_called_once_with(123, "manual_comprehensive", 999, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "mode"),
    [
        ("/report telegram", "platform_telegram"),
        ("/report x", "platform_x"),
        ("/report web", "platform_web"),
        ("/report github", "platform_github"),
        ("/report reddit", "platform_reddit"),
    ],
)
async def test_dispatch_platform_report(command, mode):
    bot = make_bot()
    bot._handle_report = AsyncMock(return_value="ok")
    bot._send_text = AsyncMock()

    result = await bot._dispatch_command(123, command, 999, 1, "message")

    assert result == "ok"
    bot._handle_report.assert_called_once_with(123, mode, 999, 1)


@pytest.mark.asyncio
async def test_dispatch_unknown_shows_menu():
    bot = make_bot()
    bot._send_menu = AsyncMock()
    result = await bot._dispatch_command(123, "/unknown", 999, 1, "message")
    assert result == "ok"
    bot._send_menu.assert_called_once()
