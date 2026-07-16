"""Partial multi-chunk delivery integration tests — real PostgreSQL.

Tests:
- Report requiring 5+ chunks
- Chunks 1-3 send successfully
- Chunk 4 fails with injected error
- Delivery persisted as partial
- Retry resumes from chunk 4
- Chunks 1-3 not sent again
- All message IDs recorded
- Final status confirmed
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from newsroom.delivery.client import ErrorCategory, TelegramAPIError
from newsroom.delivery.telegram import TelegramDelivery
from newsroom.storage.models import Delivery, DeliveryChunk, Report, ReportCursor

pytestmark = pytest.mark.integration

DEFAULT_URL = "postgresql+psycopg://newsroom:newsroom_dev@127.0.0.1:55432/newsroom"


@pytest.fixture
def db_session():
    import os
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    eng = create_engine(url, pool_pre_ping=True)
    factory = sessionmaker(bind=eng)
    session = factory()
    yield session
    session.rollback()
    session.close()
    eng.dispose()


def _cleanup(db, report_id, delivery_id=None):
    """Clean up test data in correct FK order."""
    # Reset cursor first (FK to deliveries)
    cursor = db.query(ReportCursor).filter_by(cursor_key="scheduled_delivery").first()
    if cursor:
        cursor.report_id = None
        cursor.delivery_id = None
        cursor.advanced_at = None
    # Find all deliveries for this report and delete their chunks
    deliveries = db.query(Delivery).filter_by(report_id=report_id).all()
    for d in deliveries:
        db.query(DeliveryChunk).filter_by(delivery_id=d.id).delete()
    db.query(Delivery).filter_by(report_id=report_id).delete()
    db.query(Report).filter_by(id=report_id).delete()
    db.commit()


def _make_long_report(db, content=None):
    if content is None:
        para = "این یک پاراگراف فارسی است. " * 30
        content = "\n\n".join([para] * 25)
    report = Report(
        content_fa=content,
        story_ids=[],
        report_mode="scheduled",
        generation_method="deterministic",
    )
    db.add(report)
    db.flush()
    return report


def _count_chunks(content):
    from newsroom.delivery.render import DEFAULT_CHUNK_SIZE, render_chunks
    return len(render_chunks(content, DEFAULT_CHUNK_SIZE))


class _FailOnChunk4:
    """Mock client that fails on chunk 4 (index 3)."""
    def __init__(self):
        self.token = "fake_token"
        self.send_count = 0

    async def send_message(self, chat_id, text, **kwargs):
        self.send_count += 1
        idx = self.send_count - 1
        if idx == 3:
            raise TelegramAPIError(ErrorCategory.SERVER_ERROR, "injected 500", 500)
        return {"result": {"message_id": 10000 + idx}}

    async def close(self):
        pass


class _SuccessClient:
    """Mock client that always succeeds."""
    def __init__(self, start_id=20000):
        self.token = "fake_token"
        self.send_count = 0
        self.start_id = start_id

    async def send_message(self, chat_id, text, **kwargs):
        self.send_count += 1
        return {"result": {"message_id": self.start_id + self.send_count - 1}}

    async def close(self):
        pass


class _FailOnChunk2:
    """Mock client that fails on chunk 2 (index 1)."""
    def __init__(self):
        self.token = "fake"
        self.send_count = 0

    async def send_message(self, chat_id, text, **kwargs):
        self.send_count += 1
        if self.send_count == 2:
            raise TelegramAPIError(ErrorCategory.SERVER_ERROR, "fail", 500)
        return {"result": {"message_id": 30000 + self.send_count}}

    async def close(self):
        pass


def test_partial_delivery_recovery(db_session):
    """Test partial delivery with injected failure on chunk 4, then recovery."""
    report = _make_long_report(db_session)
    chunk_count = _count_chunks(report.content_fa)
    assert chunk_count >= 5, f"Need 5+ chunks, got {chunk_count}"

    # Phase 1: fail on chunk 4
    mock1 = _FailOnChunk4()
    td = TelegramDelivery(client=mock1)
    delivery_id = asyncio.run(td.deliver_report(db_session, report.id, chat_id="test_chat"))

    delivery = db_session.query(Delivery).filter_by(id=delivery_id).first()
    assert delivery is not None
    assert delivery.status == "partial"
    assert delivery.delivered_chunks == 3
    assert delivery.total_chunks == chunk_count

    chunks = db_session.query(DeliveryChunk).filter_by(
        delivery_id=delivery_id
    ).order_by(DeliveryChunk.chunk_index).all()
    assert len(chunks) == chunk_count
    for i in range(3):
        assert chunks[i].status == "sent"
        assert chunks[i].telegram_message_id == 10000 + i
    assert chunks[3].status == "failed"
    assert chunks[3].error_category == "server_error"

    # Phase 2: retry with working client
    mock2 = _SuccessClient(start_id=20000)
    td2 = TelegramDelivery(client=mock2)
    delivery_id2 = asyncio.run(td2.deliver_report(db_session, report.id, chat_id="test_chat"))

    assert delivery_id2 == delivery_id
    db_session.expire_all()
    delivery = db_session.query(Delivery).filter_by(id=delivery_id).first()
    assert delivery.status == "delivered"
    assert delivery.delivered_at is not None

    # Chunks 1-3 not sent again
    assert mock2.send_count == chunk_count - 3

    # Verify all chunks sent
    chunks = db_session.query(DeliveryChunk).filter_by(
        delivery_id=delivery_id
    ).order_by(DeliveryChunk.chunk_index).all()
    for i in range(3):
        assert chunks[i].status == "sent"
        assert chunks[i].telegram_message_id == 10000 + i
    for i in range(3, chunk_count):
        assert chunks[i].status == "sent"
        assert chunks[i].telegram_message_id is not None

    # All message IDs recorded
    assert len(delivery.message_ids) == chunk_count

    _cleanup(db_session, report.id, delivery_id)


def test_cursor_advances_on_complete_delivery(db_session):
    """Cursor advances only after confirmed complete delivery."""
    report = _make_long_report(db_session, content="short content")

    td = TelegramDelivery(client=_SuccessClient(start_id=99999))
    asyncio.run(td.deliver_report(
        db_session, report.id, chat_id="test_chat",
        cursor_key="scheduled_delivery",
    ))

    cursor = db_session.query(ReportCursor).filter_by(
        cursor_key="scheduled_delivery"
    ).first()
    assert cursor is not None
    assert cursor.report_id == report.id

    _cleanup(db_session, report.id)


def test_cursor_does_not_advance_on_partial(db_session):
    """Partial delivery must not advance cursor."""
    content = "\n\n".join(["پاراگراف " + "x" * 800] * 6)
    report = _make_long_report(db_session, content=content)

    td = TelegramDelivery(client=_FailOnChunk2())
    asyncio.run(td.deliver_report(
        db_session, report.id, chat_id="test_chat",
        cursor_key="scheduled_delivery",
    ))

    cursor = db_session.query(ReportCursor).filter_by(
        cursor_key="scheduled_delivery"
    ).first()
    assert cursor is not None
    assert cursor.report_id is None

    _cleanup(db_session, report.id)


def test_cursor_no_double_advance(db_session):
    """Repeated confirmation cannot advance cursor twice."""
    report = _make_long_report(db_session, content="short")

    td = TelegramDelivery(client=_SuccessClient(start_id=88888))
    asyncio.run(td.deliver_report(
        db_session, report.id, chat_id="test_chat",
        cursor_key="scheduled_delivery",
    ))

    cursor = db_session.query(ReportCursor).filter_by(
        cursor_key="scheduled_delivery"
    ).first()
    assert cursor.report_id == report.id
    first_advanced_at = cursor.advanced_at

    # Second call — already delivered
    asyncio.run(td.deliver_report(
        db_session, report.id, chat_id="test_chat",
        cursor_key="scheduled_delivery",
    ))

    db_session.refresh(cursor)
    assert cursor.report_id == report.id
    assert cursor.advanced_at == first_advanced_at

    _cleanup(db_session, report.id)


def test_idempotent_delivery_no_duplicate(db_session):
    """Already-delivered report is not re-sent."""
    report = _make_long_report(db_session, content="short content")

    mock = _SuccessClient(start_id=77777)
    td = TelegramDelivery(client=mock)
    d1 = asyncio.run(td.deliver_report(db_session, report.id, chat_id="test_chat"))
    assert d1 is not None
    first_send_count = mock.send_count

    # Second attempt — idempotent
    d2 = asyncio.run(td.deliver_report(db_session, report.id, chat_id="test_chat"))
    assert d2 == d1
    assert mock.send_count == first_send_count  # No re-send

    _cleanup(db_session, report.id, d1)
