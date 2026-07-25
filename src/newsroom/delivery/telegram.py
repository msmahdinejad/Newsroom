"""Telegram delivery via Bot API — resumable multi-chunk delivery with per-chunk state.

Handles:
- Semantic chunking (render module)
- Per-chunk delivery records for partial recovery
- Error classification with bounded retry
- Cursor advancement only after confirmed complete delivery
- Idempotency: already-delivered reports are not re-sent
- Never stores the Bot Token
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from newsroom.config import settings
from newsroom.delivery.client import ErrorCategory, TelegramAPIError, TelegramBotClient
from newsroom.delivery.render import render_report_html
from newsroom.logging import get_logger
from newsroom.storage.models import Delivery, DeliveryChunk, Report, ReportCursor

logger = get_logger(__name__)

SCHEDULED_CURSOR_KEY = "scheduled_delivery"


class TelegramDelivery:
    """Deliver reports via Telegram Bot API with per-chunk recovery."""

    def __init__(self, client: TelegramBotClient | None = None) -> None:
        self.client = client or TelegramBotClient()
        self.parse_mode = settings.telegram_parse_mode

    def _hash_chat(self, chat_id: str) -> str:
        """Hash chat ID for safe storage (never store raw chat ID as key)."""
        return hashlib.sha256(chat_id.encode()).hexdigest()[:16]

    async def deliver_report(
        self,
        db: Session,
        report_id: int,
        chat_id: str | int | None = None,
        *,
        cursor_key: str | None = None,
    ) -> int | None:
        """Deliver a report with per-chunk state and partial recovery.

        Returns delivery ID on success or partial, None on total failure.
        """
        report = db.query(Report).filter_by(id=report_id).first()
        if not report:
            logger.error(f"Report {report_id} not found")
            return None

        target_chat = str(chat_id) if chat_id else settings.telegram_chat_id
        if not target_chat:
            logger.warning("No chat ID for delivery")
            return None

        chat_hash = self._hash_chat(target_chat)

        # Idempotency: check for existing delivered delivery
        existing = db.query(Delivery).filter_by(
            report_id=report_id,
            chat_id=chat_hash,
        ).first()

        if existing and existing.status == "delivered":
            logger.info(f"Report {report_id} already delivered (delivery {existing.id})")
            # Recovery boundary: a process can stop after every Telegram chunk
            # commits but before the scheduled cursor commit. Reconcile the
            # cursor on retry without sending any message again.
            if cursor_key:
                self._advance_cursor(db, cursor_key, report_id, existing.id)
                db.commit()
            return existing.id

        # Render chunks
        chunks = render_report_html(report.content_fa)

        # Create or reuse delivery record
        if existing:
            delivery = existing
            delivery.attempt_count += 1
            delivery.retry_count = delivery.retry_count or 0
        else:
            delivery = Delivery(
                report_id=report_id,
                chat_id=chat_hash,
                chat_ref=f"chat_{chat_hash[:8]}",
                total_chunks=len(chunks),
                delivered_chunks=0,
                message_ids=[],
                status="pending",
                attempt_count=1,
                retry_count=0,
                parse_mode=self.parse_mode,
            )
            db.add(delivery)
            db.flush()

        # Create or sync per-chunk records
        existing_chunks = {
            dc.chunk_index: dc for dc in db.query(DeliveryChunk).filter_by(
                delivery_id=delivery.id
            ).all()
        }

        chunk_records: list[DeliveryChunk] = []
        for i in range(len(chunks)):
            if i in existing_chunks:
                dc = existing_chunks[i]
                # Update total in case it changed
                dc.total_chunks = len(chunks)
                chunk_records.append(dc)
            else:
                dc = DeliveryChunk(
                    delivery_id=delivery.id,
                    chunk_index=i,
                    total_chunks=len(chunks),
                    status="pending",
                    attempt_count=0,
                )
                db.add(dc)
                chunk_records.append(dc)
        db.flush()

        # DeliveryChunk is authoritative. Preserve positional message IDs so
        # a restart can repair a non-contiguous gap without re-sending a later
        # chunk Telegram already confirmed.
        message_ids: list[int | None] = list(delivery.message_ids or [])
        if len(message_ids) < len(chunks):
            message_ids.extend([None] * (len(chunks) - len(message_ids)))
        for dc in chunk_records:
            if dc.status == "sent" and dc.telegram_message_id is not None:
                message_ids[dc.chunk_index] = dc.telegram_message_id

        for i, dc in enumerate(chunk_records):
            if dc.status == "sent":
                continue
            dc.attempt_count += 1
            dc.status = "pending"
            db.flush()

            try:
                response = await self.client.send_message(
                    target_chat,
                    chunks[i],
                    parse_mode=self.parse_mode,
                )
                tg_msg_id = int(response["result"]["message_id"])
                dc.telegram_message_id = tg_msg_id
                dc.status = "sent"
                dc.sent_at = datetime.now(UTC)
                dc.error_category = None
                dc.error_detail = None

                # Update delivery-level state
                message_ids[i] = tg_msg_id

                delivery.delivered_chunks = sum(
                    chunk.status == "sent" for chunk in chunk_records
                )
                delivery.message_ids = message_ids
                delivery.last_send_at = datetime.now(UTC)
                delivery.status = (
                    "delivered"
                    if delivery.delivered_chunks == len(chunks)
                    else "partial"
                )
                delivery.error = None
                delivery.error_category = None
                db.commit()

            except TelegramAPIError as e:
                dc.status = "failed"
                dc.error_category = e.category.value
                dc.error_detail = e.detail[:500]
                delivery.error = f"Chunk {i + 1}/{len(chunks)}: {e.category.value}"
                delivery.error_category = e.category.value
                delivery.status = (
                    "partial"
                    if any(chunk.status == "sent" for chunk in chunk_records)
                    else "failed"
                )
                db.commit()
                logger.error(f"Delivery chunk {i + 1} failed: {e.category.value} — {e.detail[:100]}")
                if delivery.status == "failed":
                    return None
                # Partial: return delivery ID so caller knows partial state
                return delivery.id

            except Exception as e:
                dc.status = "failed"
                dc.error_category = ErrorCategory.UNKNOWN.value
                dc.error_detail = str(e)[:500]
                delivery.error = f"Chunk {i + 1}/{len(chunks)}: {str(e)[:200]}"
                delivery.error_category = ErrorCategory.UNKNOWN.value
                delivery.status = (
                    "partial"
                    if any(chunk.status == "sent" for chunk in chunk_records)
                    else "failed"
                )
                db.commit()
                logger.error(f"Delivery chunk {i + 1} error: {e}")
                if delivery.status == "failed":
                    return None
                return delivery.id

        # All chunks sent successfully
        if delivery.status == "delivered":
            delivery.message_ids = [
                int(message_id)
                for message_id in message_ids
                if message_id is not None
            ]
            delivery.delivered_at = datetime.now(UTC)
            delivery.error = None
            delivery.error_category = None
            db.commit()

            # Advance cursor only after confirmed complete delivery
            if cursor_key:
                self._advance_cursor(db, cursor_key, report_id, delivery.id)
                db.commit()

            logger.info(
                f"Report {report_id} delivered in {len(chunks)} chunks (delivery {delivery.id})"
            )

        return delivery.id

    def _advance_cursor(
        self,
        db: Session,
        cursor_key: str,
        report_id: int,
        delivery_id: int,
    ) -> None:
        """Advance delivery cursor only after confirmed complete delivery."""
        cursor = db.query(ReportCursor).filter_by(cursor_key=cursor_key).first()
        if cursor:
            # Idempotency: don't advance to same report twice
            if cursor.report_id == report_id and cursor.delivery_id == delivery_id:
                logger.info(f"Cursor already at report {report_id} — no double-advance")
                return
            cursor.report_id = report_id
            cursor.delivery_id = delivery_id
            cursor.advanced_at = datetime.now(UTC)
        else:
            cursor = ReportCursor(
                cursor_key=cursor_key,
                report_id=report_id,
                delivery_id=delivery_id,
                advanced_at=datetime.now(UTC),
            )
            db.add(cursor)
        logger.info(f"Cursor '{cursor_key}' advanced to report {report_id}")

    async def close(self) -> None:
        await self.client.close()
