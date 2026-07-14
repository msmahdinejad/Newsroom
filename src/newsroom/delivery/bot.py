"""Telegram bot — news report commands only.

Polls for updates, handles /report /report new /report comprehensive /latest /help.
Uses inline keyboard for Persian menu. Access control via allowlist.
"""

import asyncio
import hashlib
import json
import os
import time
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from newsroom.config import settings
from newsroom.logging import get_logger, setup_logging
from newsroom.storage.database import engine, get_db
from newsroom.storage.models import Delivery, Report

logger = get_logger(__name__)

TG_API = "https://api.telegram.org/bot{token}"

# Persian inline keyboard
MENU_KEYBOARD = {
    "inline_keyboard": [
        [{"text": "گزارش فوری", "callback_data": "report_now"},
         {"text": "خبرهای جدید", "callback_data": "report_new"}],
        [{"text": "گزارش جامع فعلی", "callback_data": "report_comprehensive"},
         {"text": "آخرین گزارش", "callback_data": "latest"}],
        [{"text": "راهنمای گزارش‌ها", "callback_data": "help"}],
    ]
}


def authorized_user(user_id: int) -> bool:
    """Check if user is in the authorized allowlist."""
    allowed = settings.telegram_authorized_users
    if not allowed:
        return False
    return str(user_id) in [u.strip() for u in allowed.split(",")]


class TelegramBot:
    """News report Telegram bot."""

    def __init__(self) -> None:
        self.token = settings.telegram_bot_token
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(connect=15, read=60))
        self._offset = 0
        self._pipeline_lock = False

    def _api_url(self, method: str) -> str:
        return f"{TG_API.format(token=self.token)}/{method}"

    async def start(self) -> None:
        """Start polling loop."""
        setup_logging()
        logger.info("Starting Telegram bot")

        # Tell Telegram we're using webhook off
        await self.client.post(self._api_url("deleteWebhook"))

        while True:
            try:
                await self._poll_updates()
            except Exception as e:
                logger.error(f"Bot poll error: {e}")
                await asyncio.sleep(5)

    async def _poll_updates(self) -> None:
        """Long-poll for updates."""
        response = await self.client.post(
            self._api_url("getUpdates"),
            json={"offset": self._offset, "timeout": 30},
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            return

        for update in data.get("result", []):
            self._offset = update["update_id"] + 1
            await self._handle_update(update)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        """Route update to command or callback handler."""
        if "message" in update:
            msg = update["message"]
            user_id = msg.get("from", {}).get("id", 0)
            if not authorized_user(user_id):
                return  # silent deny

            chat_id = msg["chat"]["id"]
            cmd = msg.get("text", "").strip().lower()

            if cmd == "/start" or cmd == "/help":
                await self._send_menu(chat_id)
            elif cmd == "/report":
                await self._handle_report(chat_id, "manual")
            elif cmd == "/report new":
                await self._handle_report(chat_id, "manual_new")
            elif cmd == "/report comprehensive":
                await self._handle_report(chat_id, "manual_comprehensive")
            elif cmd == "/latest":
                await self._handle_latest(chat_id)
            else:
                await self._send_menu(chat_id)

        elif "callback_query" in update:
            cb = update["callback_query"]
            user_id = cb.get("from", {}).get("id", 0)
            if not authorized_user(user_id):
                return

            chat_id = cb["message"]["chat"]["id"]
            data = cb.get("data", "")

            # Answer callback to clear loading state
            await self.client.post(self._api_url("answerCallbackQuery"), json={"callback_query_id": cb["id"]})

            if data == "report_now":
                await self._handle_report(chat_id, "manual")
            elif data == "report_new":
                await self._handle_report(chat_id, "manual_new")
            elif data == "report_comprehensive":
                await self._handle_report(chat_id, "manual_comprehensive")
            elif data == "latest":
                await self._handle_latest(chat_id)
            elif data == "help":
                await self._send_menu(chat_id)

    async def _send_menu(self, chat_id: int) -> None:
        """Send the Persian menu."""
        help_text = (
            "🤖 راهنمای گزارش‌های خبری\n\n"
            "گزارش فوری — اخبار از آخرین گزارش زمان‌بندی‌شده\n"
            "خبرهای جدید — فقط اخبار کاملاً جدید\n"
            "گزارش جامع فعلی — گزارش گسترده فعلی\n"
            "آخرین گزارش — آخرین گزارش تولید شده\n\n"
            "⏰ زمان‌بندی خودکار: ۰۹:۰۰ | ۱۵:۰۰ | ۲۱:۰۰ (تهران)"
        )
        await self.client.post(
            self._api_url("sendMessage"),
            json={
                "chat_id": chat_id,
                "text": help_text,
                "reply_markup": MENU_KEYBOARD,
            },
        )

    async def _handle_report(self, chat_id: int, mode: str) -> None:
        """Generate and deliver a report."""
        # Check pipeline lock
        if self._pipeline_lock:
            await self._send_text(chat_id, "⏳ خط لوله در حال اجراست. لطفاً کمی بعد تلاش کنید.")
            return

        self._pipeline_lock = True
        try:
            ack = "⏳ در حال تولید گزارش..."
            await self._send_text(chat_id, ack)

            # Run pipeline in subprocess to isolate
            import subprocess
            import sys

            env = {**os.environ, "NEWSROOM_JOB_ID": f"manual_{mode}", "NEWSROOM_REPORT_MODE": mode}
            result = subprocess.run(
                [sys.executable, os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "run_pipeline.py")],
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )

            if result.returncode != 0:
                await self._send_text(chat_id, "❌ خطا در تولید گزارش.")
                return

            # Find the report ID from JSON output
            report_id = None
            for line in result.stdout.strip().split("\n"):
                if line.strip().startswith("{") and '"status"' in line:
                    try:
                        data = json.loads(line.strip())
                        if data.get("status") == "ok" and data.get("report_id"):
                            report_id = data["report_id"]
                            break
                        elif data.get("status") == "ok_empty":
                            await self._send_text(chat_id, "📭 خبر جدیدی در این دوره یافت نشد.")
                            return
                    except json.JSONDecodeError:
                        pass

            if not report_id:
                await self._send_text(chat_id, "📭 خبر جدیدی در این دوره یفت نشد.")
                return

            # Deliver the report
            from newsroom.delivery.telegram import TelegramDelivery

            td = TelegramDelivery()
            if td.configured:
                with get_db() as db:
                    delivery_id = await td.deliver_report(db, report_id, chat_id=str(chat_id))
                await td.close()
                if delivery_id:
                    await self._send_text(chat_id, f"✅ گزارش شماره {report_id} تولید و ارسال شد.")
                else:
                    await self._send_text(chat_id, f"✅ گزارش شماره {report_id} تولید شد.")
            else:
                await self._send_text(chat_id, f"✅ گزارش شماره {report_id} تولید شد (تحویل تلگرام تنظیم نشده).")

        except subprocess.TimeoutExpired:
            await self._send_text(chat_id, "❌ زمان تولید گزارش به پایان رسید.")
        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            await self._send_text(chat_id, "❌ خطا در تولید گزارش.")
        finally:
            self._pipeline_lock = False

    async def _handle_latest(self, chat_id: int) -> None:
        """Return the latest delivered report."""
        with get_db() as db:
            report = (
                db.query(Report)
                .join(Delivery, Delivery.report_id == Report.id)
                .filter(Delivery.status == "delivered")
                .order_by(Report.id.desc())
                .first()
            )
            if not report:
                # Fallback to any latest report
                report = db.query(Report).order_by(Report.id.desc()).first()

            if report:
                await self._send_text(chat_id, report.content_fa)
            else:
                await self._send_text(chat_id, "📭 هنوز گزارشی تولید نشده است.")

    async def _send_text(self, chat_id: int, text: str) -> None:
        """Send a simple text message."""
        try:
            await self.client.post(
                self._api_url("sendMessage"),
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
        except Exception as e:
            logger.error(f"Send failed: {e}")


def main() -> None:
    """Entry point for the Telegram bot service."""
    bot = TelegramBot()
    asyncio.run(bot.start())


if __name__ == "__main__":
    main()
