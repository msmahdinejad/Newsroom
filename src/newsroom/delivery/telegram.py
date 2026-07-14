"""Telegram delivery via Bot API — real implementation.

Handles chunking (4096 char limit), partial delivery recovery,
and idempotency. Stores delivery state in the deliveries table.
"""

import hashlib
import time
from datetime import UTC

import httpx
from sqlalchemy.orm import Session

from newsroom.config import settings
from newsroom.logging import get_logger
from newsroom.storage.models import Delivery, Report

logger = get_logger(__name__)

TG_API = "https://api.telegram.org/bot{token}"
MAX_MSG_LEN = 4096


class TelegramDelivery:
    """Deliver reports via Telegram Bot API."""

    def __init__(self) -> None:
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15, read=30, write=15, pool=30),
        )

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def _api_url(self, method: str) -> str:
        return f"{TG_API.format(token=self.token)}/{method}"

    async def deliver_report(
        self,
        db: Session,
        report_id: int,
        chat_id: str | None = None,
    ) -> int | None:
        """Deliver a report, handling chunking and partial recovery.

        Returns delivery ID on success, None on failure.
        """
        report = db.query(Report).filter_by(id=report_id).first()
        if not report:
            logger.error(f"Report {report_id} not found")
            return None

        target_chat = chat_id or self.chat_id
        if not self.configured or not target_chat:
            logger.warning("Telegram not configured — delivery skipped")
            return None

        # Check for existing delivery (idempotency)
        existing = db.query(Delivery).filter_by(
            report_id=report_id,
            chat_id=self._hash_chat(target_chat),
        ).first()

        if existing and existing.status == "delivered":
            logger.info(f"Report {report_id} already delivered")
            return existing.id

        chunks = self._split_message(report.content_fa)

        # Create or update delivery record
        if existing:
            delivery = existing
            # Resume from delivered_chunks
        else:
            delivery = Delivery(
                report_id=report_id,
                chat_id=self._hash_chat(target_chat),
                total_chunks=len(chunks),
                delivered_chunks=0,
                message_ids=[],
                status="pending",
            )
            db.add(delivery)
            db.flush()

        message_ids: list[int] = list(delivery.message_ids or [])
        start_idx = delivery.delivered_chunks

        for i in range(start_idx, len(chunks)):
            chunk = chunks[i]
            try:
                msg_id = await self._send_message(target_chat, chunk)
                message_ids.append(msg_id)
                delivery.delivered_chunks = i + 1
                delivery.message_ids = message_ids
                delivery.status = "partial" if i < len(chunks) - 1 else "delivered"
                db.commit()

                # Rate limit: ~25 msg/sec, but be conservative
                if i < len(chunks) - 1:
                    time.sleep(0.5)

            except httpx.HTTPStatusError as e:
                delivery.error = f"Chunk {i+1}/{len(chunks)}: {e.response.status_code}"
                delivery.status = "failed" if i == 0 else "partial"
                db.commit()
                logger.error(f"Delivery chunk {i+1} failed: {e}")
                return delivery.id if delivery.status == "partial" else None

            except Exception as e:
                delivery.error = str(e)[:500]
                delivery.status = "failed" if i == 0 else "partial"
                db.commit()
                logger.error(f"Delivery chunk {i+1} error: {e}")
                return delivery.id if delivery.status == "partial" else None

        if delivery.status == "delivered":
            from datetime import datetime
            delivery.delivered_at = datetime.now(UTC)
            db.commit()
            logger.info(f"Report {report_id} delivered in {len(chunks)} chunks")

        return delivery.id

    async def _send_message(self, chat_id: str, text: str) -> int:
        """Send a single message. Returns Telegram message_id."""
        response = await self.client.post(
            self._api_url("sendMessage"),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data.get('description', 'unknown')}")
        return data["result"]["message_id"]

    def _hash_chat(self, chat_id: str) -> str:
        """Hash chat ID for safe storage."""
        return hashlib.sha256(chat_id.encode()).hexdigest()[:16]

    def _split_message(self, text: str, max_length: int = MAX_MSG_LEN) -> list[str]:
        """Split message into Telegram-safe chunks, preserving semantic units."""
        if len(text) <= max_length:
            return [text]

        chunks: list[str] = []
        lines = text.split("\n")
        current: list[str] = []
        current_len = 0

        for line in lines:
            line_len = len(line) + 1
            if current_len + line_len > max_length and current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0

            if line_len > max_length:
                # Split very long lines by words
                words = line.split(" ")
                temp: list[str] = []
                temp_len = 0
                for word in words:
                    word_len = len(word) + 1
                    if temp_len + word_len > max_length and temp:
                        chunks.append(" ".join(temp))
                        temp = [word]
                        temp_len = word_len
                    else:
                        temp.append(word)
                        temp_len += word_len
                if temp:
                    current = temp
                    current_len = sum(len(w) + 1 for w in temp)
            else:
                current.append(line)
                current_len += line_len

        if current:
            chunks.append("\n".join(current))

        return chunks

    async def close(self) -> None:
        await self.client.aclose()
