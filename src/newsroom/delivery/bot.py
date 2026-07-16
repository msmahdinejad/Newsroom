"""Telegram bot — news report commands only.

When TELEGRAM_BOT_ENABLED is false or token missing: idle with status
blocked_by_credentials / disabled — no network auth, no crash-loop.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

from newsroom.config import settings
from newsroom.logging import get_logger, setup_logging
from newsroom.storage.database import get_db
from newsroom.storage.models import Delivery, Report

logger = get_logger(__name__)

TG_API = "https://api.telegram.org/bot{token}"

MENU_KEYBOARD = {
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


def authorized_user(user_id: int) -> bool:
    allowed = settings.telegram_authorized_users
    if not allowed:
        return False
    return str(user_id) in [u.strip() for u in allowed.split(",")]


def bot_service_status() -> dict[str, Any]:
    if not settings.telegram_bot_enabled:
        return {"status": "disabled", "feature": "telegram_bot"}
    if not settings.telegram_bot_token:
        return {"status": "blocked_by_credentials", "feature": "telegram_bot", "missing": "TELEGRAM_BOT_TOKEN"}
    return {"status": "enabled", "feature": "telegram_bot"}


class TelegramBot:
    def __init__(self) -> None:
        self.token = settings.telegram_bot_token
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15, read=60, write=30, pool=30)
        )
        self._offset = 0

    def _api_url(self, method: str) -> str:
        return f"{TG_API.format(token=self.token)}/{method}"

    async def start(self) -> None:
        setup_logging()
        status = bot_service_status()
        if status["status"] != "enabled":
            logger.info(f"Telegram bot {status['status']} — idle (no network auth)")
            # write status for healthcheck
            try:
                with open("/tmp/newsroom_bot_status.json", "w", encoding="utf-8") as f:
                    json.dump(status, f)
            except OSError:
                pass
            while True:
                await asyncio.sleep(3600)
            return

        logger.info("Starting Telegram bot")
        try:
            with open("/tmp/newsroom_bot_status.json", "w", encoding="utf-8") as f:
                json.dump(status, f)
        except OSError:
            pass

        await self.client.post(self._api_url("deleteWebhook"))
        while True:
            try:
                await self._poll_updates()
            except Exception as e:
                logger.error(f"Bot poll error: {e}")
                await asyncio.sleep(5)

    async def _poll_updates(self) -> None:
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
        if "message" in update:
            msg = update["message"]
            user_id = msg.get("from", {}).get("id", 0)
            if not authorized_user(user_id):
                return
            chat_id = msg["chat"]["id"]
            cmd = msg.get("text", "").strip().lower()
            if cmd in ("/start", "/help"):
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
            await self.client.post(
                self._api_url("answerCallbackQuery"),
                json={"callback_query_id": cb["id"]},
            )
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
            json={"chat_id": chat_id, "text": help_text, "reply_markup": MENU_KEYBOARD},
        )

    async def _handle_report(self, chat_id: int, mode: str) -> None:
        """Run authoritative pipeline (Postgres lock inside runner)."""
        await self._send_text(chat_id, "⏳ در حال تولید گزارش...")
        env = {
            **os.environ,
            "NEWSROOM_JOB_ID": f"manual_{mode}_{chat_id}",
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
            await self._send_text(chat_id, "❌ خطا در تولید گزارش.")
            return

        if result.get("status") == "busy":
            await self._send_text(chat_id, "⏳ خط لوله در حال اجراست. لطفاً کمی بعد تلاش کنید.")
            return
        if result.get("status") == "ok_empty":
            await self._send_text(chat_id, "📭 خبر جدیدی در این دوره یافت نشد.")
            return
        if result.get("status") != "ok":
            await self._send_text(chat_id, "❌ خطا در تولید گزارش.")
            return

        report_id = result.get("report_id")
        if not report_id:
            await self._send_text(chat_id, "📭 خبر جدیدی در این دوره یافت نشد.")
            return

        if settings.telegram_bot_ready():
            from newsroom.delivery.telegram import TelegramDelivery

            td = TelegramDelivery()
            try:
                with get_db() as db:
                    delivery_id = await td.deliver_report(db, report_id, chat_id=str(chat_id))
                if delivery_id:
                    await self._send_text(chat_id, f"✅ گزارش شماره {report_id} تولید و ارسال شد.")
                else:
                    await self._send_text(chat_id, f"✅ گزارش شماره {report_id} تولید شد.")
            finally:
                await td.close()
        else:
            await self._send_text(
                chat_id, f"✅ گزارش شماره {report_id} تولید شد (تحویل تلگرام تنظیم نشده)."
            )

    async def _handle_latest(self, chat_id: int) -> None:
        with get_db() as db:
            report = (
                db.query(Report)
                .join(Delivery, Delivery.report_id == Report.id)
                .filter(Delivery.status == "delivered")
                .order_by(Report.id.desc())
                .first()
            )
            if not report:
                report = db.query(Report).order_by(Report.id.desc()).first()
            if report:
                await self._send_text(chat_id, report.content_fa)
            else:
                await self._send_text(chat_id, "📭 هنوز گزارشی تولید نشده است.")

    async def _send_text(self, chat_id: int, text: str) -> None:
        try:
            await self.client.post(
                self._api_url("sendMessage"),
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            )
        except Exception as e:
            logger.error(f"Send failed: {e}")


def main() -> None:
    bot = TelegramBot()
    asyncio.run(bot.start())


if __name__ == "__main__":
    main()
