"""Deterministic tests for digest-local scheduling and status commands.

Covers:
  * the default digest keeps its 00/06/12/18 local-time preset;
  * status command helpers build safe summaries (no secrets);
  * bot dispatch routes /status /collect /sources /schedule;
  * help text reflects the new schedule and excludes secrets.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from newsroom.delivery.bot import HELP_TEXT, TelegramBot
from newsroom.delivery.status_commands import (
    schedule_text,
    sources_text,
    status_text,
)
from newsroom.scheduler import (
    JOB_IDS,
    SCHEDULE_HOURS,
    DigestSchedule,
    create_scheduler,
    reconcile_digest_schedules,
    registered_job_ids,
    scheduled_specs,
)

# ── Scheduler specs ───────────────────────────────────────────────


def test_schedule_hours_are_four_six_hour_boundaries():
    assert SCHEDULE_HOURS == (0, 6, 12, 18)


def test_job_ids_match_hours():
    assert JOB_IDS == ("report_00", "report_06", "report_12", "report_18")


def test_scheduled_specs_count_and_hours():
    specs = scheduled_specs()
    assert len(specs) == 4
    assert [s[1] for s in specs] == [0, 6, 12, 18]
    assert all(s[2] == 0 for s in specs)  # minute = 0
    assert [s[0] for s in specs] == list(JOB_IDS)


def test_scheduled_specs_support_owner_minutes_and_disabled_schedule():
    specs = scheduled_specs(("01:15", "13:45"))
    assert [(item[0], item[1], item[2], item[3]) for item in specs] == [
        ("report_0115", 1, 15, "01:15"),
        ("report_1345", 13, 45, "13:45"),
    ]
    assert scheduled_specs(()) == []


def test_explicit_empty_digest_schedule_registers_no_jobs():
    scheduler = create_scheduler(digest_schedules=())

    assert registered_job_ids(scheduler) == []


def test_schedule_reconciliation_detects_timezone_change_at_same_job_id():
    original = (
        DigestSchedule(
            slug="world",
            name="World briefing",
            timezone="Europe/Berlin",
            times=("08:00",),
        ),
    )
    scheduler = create_scheduler(digest_schedules=original)

    assert reconcile_digest_schedules(scheduler, original) is False
    changed = (
        DigestSchedule(
            slug="world",
            name="World briefing",
            timezone="Asia/Tokyo",
            times=("08:00",),
        ),
    )
    assert reconcile_digest_schedules(scheduler, changed) is True
    assert registered_job_ids(scheduler) == ["report_world_08"]
    assert str(scheduler.get_job("report_world_08").trigger.timezone) == "Asia/Tokyo"


def test_help_text_reflects_six_hour_schedule():
    assert "\u06f1\u06f8:\u06f0\u06f0" in HELP_TEXT
    assert "\u06f0\u06f9:\u06f0\u06f0" not in HELP_TEXT  # old schedule removed


def test_help_text_mentions_new_commands():
    for cmd in (
        "/status",
        "/sources",
        "/collect",
        "/schedule",
        "/settings language",
        "/source enable",
        "/sources import",
    ):
        assert cmd in HELP_TEXT


# ── Status commands (no secrets) ───────────────────────────────────


def _mock_db_with_inventory():
    db = MagicMock()
    # inventory_totals: db.query(SourceInventory).count() + .all()
    q = MagicMock()
    q.count.return_value = 2
    inv_rows = []
    for plat, state in [("Telegram", "active"), ("X / Twitter", "inactive")]:
        m = MagicMock()
        m.operational_state = state
        m.platform = plat
        m.inactive_reason = "x_auth_not_configured" if state == "inactive" else None
        inv_rows.append(m)
    q.all.return_value = inv_rows
    db.query.return_value = q
    return db


def test_status_text_has_no_secrets():
    db = _mock_db_with_inventory()
    text = status_text(db)
    low = text.lower()
    for secret in ("token", "api_key", "password", "session", ".env", "phone"):
        assert secret not in low, f"leaked {secret}"
    assert "\u0648\u0636\u0639\u06cc\u062a" in text


def test_sources_text_lists_platforms():
    db = _mock_db_with_inventory()
    text = sources_text(db)
    assert "Telegram" in text
    assert "X / Twitter" in text
    assert "x_auth_not_configured" in text


def test_schedule_text_shows_boundaries():
    db = MagicMock()
    text = schedule_text(db)
    for t in (
        "\u06f0\u06f0:\u06f0\u06f0",
        "\u06f0\u06f6:\u06f0\u06f0",
        "\u06f1\u06f2:\u06f0\u06f0",
        "\u06f1\u06f8:\u06f0\u06f0",
    ):
        assert t in text


# ── Bot dispatch of new commands ──────────────────────────────────


def make_bot():
    bot = TelegramBot.__new__(TelegramBot)
    bot.api = AsyncMock()
    bot._offset = 0
    bot._last_update_ts = None
    bot._last_delivery_ts = None
    bot._bot_info = None
    bot._polling_alive = False
    return bot


@pytest.mark.asyncio
async def test_dispatch_status():
    bot = make_bot()
    bot._handle_status = AsyncMock(return_value="ok")
    result = await bot._dispatch_command(123, "/status", 999, 1, "message")
    assert result == "ok"
    bot._handle_status.assert_called_once_with(123)


@pytest.mark.asyncio
async def test_dispatch_sources():
    bot = make_bot()
    bot._handle_sources = AsyncMock(return_value="ok")
    result = await bot._dispatch_command(123, "/sources", 999, 1, "message")
    assert result == "ok"
    bot._handle_sources.assert_called_once_with(123)


@pytest.mark.asyncio
async def test_dispatch_collect():
    bot = make_bot()
    bot._handle_collect = AsyncMock(return_value="ok")
    result = await bot._dispatch_command(123, "/collect", 999, 1, "message")
    assert result == "ok"
    bot._handle_collect.assert_called_once_with(123)


@pytest.mark.asyncio
async def test_dispatch_schedule():
    bot = make_bot()
    bot._handle_schedule = MagicMock(return_value="ok")
    result = await bot._dispatch_command(123, "/schedule", 999, 1, "message")
    assert result == "ok"
    bot._handle_schedule.assert_called_once_with(123)


@pytest.mark.asyncio
async def test_dispatch_settings_and_source_import():
    bot = make_bot()
    bot._handle_settings = AsyncMock(return_value="ok")
    bot._handle_source_import = AsyncMock(return_value="ok")
    document = {"file_id": "safe-id", "file_name": "sources.csv"}

    settings_result = await bot._dispatch_command(
        123,
        "/settings language en",
        999,
        2,
        "message",
    )
    import_result = await bot._dispatch_command(
        123,
        "/sources import",
        999,
        3,
        "message",
        document=document,
    )

    assert settings_result == "ok"
    assert import_result == "ok"
    bot._handle_settings.assert_awaited_once_with(123, "/settings language en")
    bot._handle_source_import.assert_awaited_once_with(123, document)


@pytest.mark.asyncio
async def test_dispatch_named_digest_report():
    bot = make_bot()
    bot._handle_report = AsyncMock(return_value="ok")

    result = await bot._dispatch_command(
        123,
        "/report digest climate telegram",
        999,
        4,
        "message",
    )

    assert result == "ok"
    bot._handle_report.assert_awaited_once_with(
        123,
        "platform_telegram",
        999,
        4,
        digest_slug="climate",
    )
