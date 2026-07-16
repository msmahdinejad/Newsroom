"""Telegram bot — news report commands with access control and idempotency.

When TELEGRAM_BOT_ENABLED is false or token missing: idle with status
disabled/blocked — no network auth, no crash-loop.

Sole Bot API polling owner. No other process uses the token.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import UTC, datetime
from typing import Any

from newsroom.config import settings
from newsroom.delivery.access import deny_message, is_authorized
from newsroom.delivery.client import TelegramBotClient, redact_token
from newsroom.delivery.telegram import TelegramDelivery
from newsroom.logging import get_logger, setup_logging
from newsroom.storage.database import get_db
from newsroom.storage.models import (
    CommandRequest,
    Delivery,
    Report,
    TelegramUpdate,
)

logger = get_logger(__name__)

MENU_KEYBOARD: dict[str, Any] = {
    "inline_keyboard": [
        [
            {"text": "گزارش فوری", "callback_data": "report_now"},
            {"text": "خبرهای جدید", "callback_data": "report_new"},
        ],
        [
            {"text": "گزارش جامع فعلی", "callback_data": "report_comprehensive"},
            {"text": "آخرین گزارش", "callback_data": "latest"},
        ],
        [{"text": "راهنمای گزارش‌ها", "callback_data": "help"}],
    ]
}

HELP_TEXT = (
    "🤖 راهنمای گزارش‌های خبری\n\n"
    "گزارش فوری — اخبار از آخرین گزارش زمان‌بندی‌شده\n"
    "خبرهای جدید — فقط اخبار کاملاً جدید\n"
    "گزارش جامع فعلی — گزارش گسترده فعلی\n"
    "آخرین گزارش — آخرین گزارش تولید شده\n\n"
    "⏰ زمان‌بندی خودکار: ۰۹:۰۰ | ۱۵:۰۰ | ۲۱:۰۰ (تهران)"
)

# Max update_id offset stored to survive restart
_STATUS_FILE = "/tmp/newsroom_bot_status.json"


def _bot_service_status() -> dict[str, Any]:
    if not settings.telegram_bot_enabled:
        return {"status": "disabled", "feature": "telegram_bot"}
    if not settings.telegram_bot_token:
        return {
            "status": "blocked_by_credentials",
            "feature": "telegram_bot",
            "missing": "TELEGRAM_BOT_TOKEN",
        }
    return {"status": "enabled", "feature": "telegram_bot"}


def _write_status(payload: dict[str, Any]) -> None:
    try:
        with open(_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except OSError:
        pass


def _read_status() -> dict[str, Any]:
    try:
        with open(_STATUS_FILE, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
        return data
    except Exception:
        return {}


class TelegramBot:
    """Sole Bot API polling owner with command idempotency and access control."""

    def __init__(self) -> None:
        self.api = TelegramBotClient()
        self._offset = 0
        self._last_update_ts: datetime | None = None
        self._last_delivery_ts: datetime | None = None
        self._bot_info: dict[str, Any] | None = None
        self._polling_alive = False

    async def start(self) -> None:
        setup_logging()
        status = _bot_service_status()

        if status["status"] != "enabled":
            logger.info(f"Telegram bot {status['status']} — idle (no network auth)")
            health = self._health_payload(status)
            _write_status(health)
            while True:
                await asyncio.sleep(3600)
            return

        logger.info("Starting Telegram bot (sole polling owner)")
        _write_status(self._health_payload(status))

        # Verify bot identity
        try:
            me = await self.api.get_me()
            self._bot_info = me.get("result", {})
            logger.info(
                f"Bot identity: @{self._bot_info.get('username', '?')} "
                f"({redact_token(settings.telegram_bot_token)})"
            )
        except Exception as e:
            logger.error(f"Bot identity query failed: {e}")
            _write_status(self._health_payload({
                **status,
                "degraded": ["identity_query_failed"],
            }))

        # Clear any webhook to ensure polling works
        await self.api.delete_webhook()

        self._polling_alive = True
        while True:
            try:
                await self._poll_updates()
                _write_status(self._health_payload(status))
            except Exception as e:
                self._polling_alive = False
                logger.error(f"Bot poll error: {e}")
                _write_status(self._health_payload({
                    **status,
                    "degraded": ["poll_error"],
                }))
                await asyncio.sleep(5)
                self._polling_alive = True

    async def _poll_updates(self) -> None:
        response = await self.api.get_updates(offset=self._offset)
        if not response.get("ok"):
            return
        for update in response.get("result", []):
            self._offset = update["update_id"] + 1
            await self._handle_update(update)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        update_id = update["update_id"]
        update_type = "message" if "message" in update else "callback"

        # Idempotency: check if we already processed this update_id
        with get_db() as db:
            existing = db.query(TelegramUpdate).filter_by(update_id=update_id).first()
            if existing:
                logger.info(f"Update {update_id} already processed ({existing.result}) — skipping")
                return

        # Parse update
        if "message" in update:
            msg = update["message"]
            user_id = msg.get("from", {}).get("id")
            chat_id = msg["chat"]["id"]
            text = msg.get("text", "").strip()
            command = text.lower() if text else ""
        elif "callback_query" in update:
            cb = update["callback_query"]
            user_id = cb.get("from", {}).get("id")
            chat_id = cb["message"]["chat"]["id"]
            command = cb.get("data", "")
            # Answer the callback query to remove the loading spinner
            with contextlib.suppress(Exception):
                await self.api.answer_callback_query(cb["id"])
        else:
            return

        self._last_update_ts = datetime.now(UTC)

        # Access control — checked on EVERY update, not just /start
        if not is_authorized(user_id):
            self._record_update(update_id, update_type, user_id, chat_id, command, "denied")
            # Deny without infrastructure details
            with contextlib.suppress(Exception):
                await self.api.send_message(chat_id, deny_message())
            return

        # Process command
        result = await self._dispatch_command(chat_id, command, user_id, update_id, update_type)

        self._record_update(update_id, update_type, user_id, chat_id, command, result)
        if result == "ok" and "deliver" in command:
            self._last_delivery_ts = datetime.now(UTC)

    def _record_update(
        self,
        update_id: int,
        update_type: str,
        user_id: int | None,
        chat_id: int | str | None,
        command: str,
        result: str,
    ) -> None:
        """Persist update idempotency record."""
        try:
            with get_db() as db:
                existing = db.query(TelegramUpdate).filter_by(update_id=update_id).first()
                if existing:
                    return
                db.add(TelegramUpdate(
                    update_id=update_id,
                    update_type=update_type,
                    user_id=user_id,
                    chat_id=str(chat_id) if chat_id else None,
                    command=command[:100],
                    result=result,
                ))
        except Exception as e:
            logger.error(f"Failed to record update {update_id}: {e}")

    async def _dispatch_command(
        self,
        chat_id: int | str,
        command: str,
        user_id: int | None,
        update_id: int,
        update_type: str,
    ) -> str:
        """Route command to handler. Returns result string."""
        cmd = command.lower().strip()

        if cmd in ("/start", "/help", "help"):
            await self._send_menu(chat_id)
            return "ok"

        if cmd == "/latest" or cmd == "latest":
            return await self._handle_latest(chat_id)

        if cmd in ("/report", "/report new", "/report comprehensive") or cmd in (
            "report_now", "report_new", "report_comprehensive"
        ):
            # Map command to pipeline mode
            mode_map = {
                "/report": "manual",
                "report_now": "manual",
                "/report new": "manual_new",
                "report_new": "manual_new",
                "/report comprehensive": "manual_comprehensive",
                "report_comprehensive": "manual_comprehensive",
            }
            mode = mode_map.get(cmd, "manual")
            return await self._handle_report(chat_id, mode, user_id, update_id)

        # Unknown command — show menu
        await self._send_menu(chat_id)
        return "ok"

    async def _send_menu(self, chat_id: int | str) -> None:
        try:
            await self.api.send_message(
                chat_id,
                HELP_TEXT,
                reply_markup=MENU_KEYBOARD,
            )
        except Exception as e:
            logger.error(f"Send menu failed: {e}")

    async def _handle_latest(self, chat_id: int | str) -> str:
        """Return latest persisted report — no collection, no generation."""
        try:
            with get_db() as db:
                # Prefer latest delivered report
                report = (
                    db.query(Report)
                    .join(Delivery, Delivery.report_id == Report.id)
                    .filter(Delivery.status == "delivered")
                    .order_by(Report.id.desc())
                    .first()
                )
                if not report:
                    # Fallback: latest report of any kind
                    report = db.query(Report).order_by(Report.id.desc()).first()

                if report:
                    from newsroom.delivery.render import render_report_html
                    chunks = render_report_html(report.content_fa)
                    for chunk in chunks:
                        await self.api.send_message(
                            chat_id,
                            chunk,
                            parse_mode=settings.telegram_parse_mode,
                        )
                    return "ok"
                else:
                    await self.api.send_message(chat_id, "📭 هنوز گزارشی تولید نشده است.")
                    return "ok"
        except Exception as e:
            logger.error(f"/latest failed: {e}")
            with contextlib.suppress(Exception):
                await self.api.send_message(chat_id, "❌ خطا در بازیابی گزارش.")
            return "error"

    async def _handle_report(
        self,
        chat_id: int | str,
        mode: str,
        user_id: int | None,
        update_id: int,
    ) -> str:
        """Run pipeline under PostgreSQL lock with command idempotency."""
        # Build request key for idempotency
        # Same command from same user within active window = busy/idempotent
        request_key = f"{mode}_{user_id}_{chat_id}"

        with get_db() as db:
            existing_req = db.query(CommandRequest).filter_by(request_key=request_key).first()
            if existing_req and existing_req.status == "running":
                await self._send_text(chat_id, "⏳ در حال تولید گزارش...")
                return "busy"
            if existing_req and existing_req.status == "ok" and existing_req.report_id:
                # Already completed — return existing report
                report_id = existing_req.report_id
                db.close()
                await self._send_text(chat_id, f"✅ گزارش شماره {report_id} از قبل تولید شده است.")
                return "ok"
            # Create or update request
            if existing_req:
                existing_req.status = "running"
                existing_req.finished_at = None
            else:
                req = CommandRequest(
                    request_key=request_key,
                    command=mode,
                    user_id=user_id,
                    chat_id=str(chat_id),
                    status="running",
                )
                db.add(req)
                db.flush()

        await self._send_text(chat_id, "⏳ در حال تولید گزارش...")

        # Run pipeline via authoritative runner
        env = {
            **os.environ,
            "NEWSROOM_JOB_ID": f"manual_{mode}_{update_id}",
            "NEWSROOM_REPORT_MODE": mode,
        }
        loop = asyncio.get_running_loop()

        def _run() -> dict:
            os.environ.update(env)
            from newsroom.pipeline.runner import run_pipeline
            return run_pipeline()

        try:
            result = await loop.run_in_executor(None, _run)
        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            self._finish_request(request_key, "error", None, None)
            await self._send_text(chat_id, "❌ خطا در تولید گزارش.")
            return "error"

        if result.get("status") == "busy":
            self._finish_request(request_key, "busy", None, None)
            await self._send_text(chat_id, "⏳ خط لوله در حال اجراست. لطفاً کمی بعد تلاش کنید.")
            return "busy"

        if result.get("status") == "ok_empty":
            self._finish_request(request_key, "ok", None, None)
            await self._send_text(chat_id, "📭 خبر جدیدی در این دوره یافت نشد.")
            return "ok"

        if result.get("status") != "ok":
            self._finish_request(request_key, "error", None, None)
            await self._send_text(chat_id, "❌ خطا در تولید گزارش.")
            return "error"

        result_report_id = result.get("report_id")
        if not result_report_id:
            self._finish_request(request_key, "ok", None, None)
            await self._send_text(chat_id, "📭 خبر جدیدی در این دوره یافت نشد.")
            return "ok"

        # Deliver the report
        delivery_id: int | None = None
        if settings.telegram_bot_ready():
            td = TelegramDelivery()
            try:
                with get_db() as db:
                    delivery_id = await td.deliver_report(
                        db, result_report_id, chat_id=chat_id
                    )
            finally:
                await td.close()

        self._finish_request(request_key, "ok", result_report_id, delivery_id)

        if delivery_id:
            await self._send_text(chat_id, f"✅ گزارش شماره {result_report_id} تولید و ارسال شد.")
        else:
            await self._send_text(
                chat_id, f"✅ گزارش شماره {result_report_id} تولید شد (تحویل تلگرام تنظیم نشده)."
            )
        return "ok"

    def _finish_request(
        self,
        request_key: str,
        status: str,
        report_id: int | None,
        delivery_id: int | None,
    ) -> None:
        """Update command request record."""
        try:
            with get_db() as db:
                req = db.query(CommandRequest).filter_by(request_key=request_key).first()
                if req:
                    req.status = status
                    req.report_id = report_id
                    req.delivery_id = delivery_id
                    req.finished_at = datetime.now(UTC)
        except Exception as e:
            logger.error(f"Failed to finish request {request_key}: {e}")

    async def _send_text(self, chat_id: int | str, text: str) -> None:
        try:
            await self.api.send_message(chat_id, text)
        except Exception as e:
            logger.error(f"Send failed: {e}")

    def _health_payload(self, base_status: dict[str, Any]) -> dict[str, Any]:
        """Deep health check — more than process existence."""
        from newsroom.storage.database import db_health

        payload: dict[str, Any] = {
            **base_status,
            "timestamp": datetime.now(UTC).isoformat(),
            "polling_alive": self._polling_alive,
            "last_update": self._last_update_ts.isoformat() if self._last_update_ts else None,
            "last_delivery": self._last_delivery_ts.isoformat() if self._last_delivery_ts else None,
        }

        # DB connectivity
        payload["db_connected"] = db_health()

        # Authorized users nonempty
        allowed = settings.authorized_user_ids()
        payload["authorized_users_count"] = len(allowed)

        # Bot identity
        if self._bot_info:
            payload["bot_username"] = self._bot_info.get("username")

        # Degraded conditions
        degraded = []
        if base_status.get("status") == "enabled":
            if not payload["db_connected"]:
                degraded.append("database")
            if not allowed:
                degraded.append("empty_allowlist")
            if not self._polling_alive:
                degraded.append("polling_dead")
        if degraded:
            payload["degraded"] = degraded

        return payload


def main() -> None:
    bot = TelegramBot()
    asyncio.run(bot.start())


if __name__ == "__main__":
    main()
