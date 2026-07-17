"""Gate 3 PostgreSQL integration tests — real DB, no MagicMock sessions.

Tests: channel persistence, unique identity, username updates, message
identity constraints, cursor persistence, edit behavior, forward attribution,
gap records, health states, pipeline processing.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.integration

DEFAULT_URL = "postgresql+psycopg://newsroom:newsroom_dev@127.0.0.1:55432/newsroom"


@pytest.fixture(scope="module")
def engine():
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    eng = create_engine(url, pool_pre_ping=True)
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    factory = sessionmaker(bind=engine)
    session = factory()
    # Clean telegram-specific tables before each test
    session.execute(text("DELETE FROM telegram_message_gaps"))
    session.execute(text("DELETE FROM telegram_channels"))
    session.execute(text("DELETE FROM collection_cursors WHERE cursor_key LIKE 'tg_%'"))
    # Clean telegram raw items
    session.execute(text("DELETE FROM raw_items WHERE telegram_channel_id IS NOT NULL"))
    session.execute(text("DELETE FROM sources WHERE type = 'telegram'"))
    session.commit()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def _make_telegram_source(session, name="telegram_test", tg_id=123456, username="testchannel"):
    """Insert a telegram source + telegram_channel row."""
    from newsroom.storage.models import Source, TelegramChannel
    src = Source(
        name=name, type="telegram",
        url=f"https://t.me/{username}",
        enabled=True,
        config={"channel_username": username, "telegram_channel_id": tg_id},
        health_status="configured",
    )
    session.add(src)
    session.flush()
    ch = TelegramChannel(
        source_id=src.id, telegram_channel_id=tg_id,
        public_username=username, display_name="Test Channel",
        source_state="configured", enabled=True,
    )
    session.add(ch)
    session.flush()
    return src, ch


# ── Schema ───────────────────────────────────────────────────

def test_gate3_tables_exist(engine):
    insp = inspect(engine)
    tables = insp.get_table_names()
    assert "telegram_channels" in tables
    assert "telegram_message_gaps" in tables

def test_telegram_channels_unique_id(engine):
    insp = inspect(engine)
    idxs = insp.get_indexes("telegram_channels")
    unique = [i for i in idxs if i["unique"]]
    assert any(i["column_names"] == ["telegram_channel_id"] for i in unique)

def test_raw_items_telegram_identity_unique(engine):
    insp = inspect(engine)
    idxs = insp.get_indexes("raw_items")
    unique = [i for i in idxs if i["unique"]]
    assert any("telegram_channel_id" in i["column_names"] and "telegram_message_id" in i["column_names"] for i in unique)

def test_alembic_at_gate3_revision(engine):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
    assert row is not None
    assert row[0] == "0004_gate3_mtproto"


# ── Channel persistence & identity ───────────────────────────

def test_channel_source_persisted(db):
    src, ch = _make_telegram_source(db)
    assert ch.id is not None
    assert ch.telegram_channel_id == 123456
    assert ch.public_username == "testchannel"

def test_unique_telegram_channel_id(db):
    _make_telegram_source(db, tg_id=100, name="ch1")
    from sqlalchemy.exc import IntegrityError

    from newsroom.storage.models import TelegramChannel
    dup = TelegramChannel(
        source_id=999, telegram_channel_id=100,
        public_username="other", source_state="candidate",
    )
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

def test_username_update_no_duplicate_source(db):
    """Changing username must not create a duplicate source row."""
    src, ch = _make_telegram_source(db, tg_id=200, username="old_name")
    original_source_id = src.id
    # Simulate username change
    ch.public_username = "new_name"
    src.url = "https://t.me/new_name"
    src.config["channel_username"] = "new_name"
    db.commit()
    # Verify no duplicate
    from newsroom.storage.models import Source, TelegramChannel
    sources = db.query(Source).filter_by(type="telegram", enabled=True).all()
    tg_sources = [s for s in sources if s.config.get("telegram_channel_id") == 200]
    assert len(tg_sources) == 1
    assert tg_sources[0].id == original_source_id
    channels = db.query(TelegramChannel).filter_by(telegram_channel_id=200).all()
    assert len(channels) == 1
    assert channels[0].public_username == "new_name"


# ── Message identity & cursor ────────────────────────────────

def test_message_identity_constraint(db):
    """Same (channel_id, message_id) must not create two raw items."""
    from newsroom.storage.models import RawItem
    src, ch = _make_telegram_source(db, tg_id=300)
    item1 = RawItem(
        source_id=src.id, raw_data={"type": "telegram", "text": "v1"},
        content_hash="h1", telegram_channel_id=300, telegram_message_id=50,
    )
    db.add(item1)
    db.commit()
    item2 = RawItem(
        source_id=src.id, raw_data={"type": "telegram", "text": "v2"},
        content_hash="h2", telegram_channel_id=300, telegram_message_id=50,
    )
    db.add(item2)
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

def test_cursor_persistence(db):
    from newsroom.pipeline.cursors import load_cursor, save_cursor
    src, _ = _make_telegram_source(db, tg_id=400)
    save_cursor(db, src.id, {"last_message_id": "500"}, key="tg_default")
    db.commit()
    loaded = load_cursor(db, src.id, key="tg_default")
    assert loaded.get("last_message_id") == "500"


# ── Edit behavior ────────────────────────────────────────────

def test_edit_updates_existing_item(db):
    from newsroom.sources.telegram_adapter import compute_content_hash
    from newsroom.sources.telegram_collector import TelegramMTProtoCollector
    src, ch = _make_telegram_source(db, tg_id=500)
    coll = TelegramMTProtoCollector()

    item_v1 = {
        "type": "telegram", "source_id": src.id, "source_name": "test",
        "source_url": src.url, "telegram_channel_id": 500, "message_id": 100,
        "text": "original", "date": "2026-07-17T10:00:00+00:00",
        "edit_date": None, "link": "https://t.me/test/100",
        "content_hash": compute_content_hash("original", 500, 100),
    }
    stats = coll.persist_items(db, src, [item_v1])
    db.commit()
    assert stats["new"] == 1

    item_v2 = dict(item_v1)
    item_v2["text"] = "edited text"
    item_v2["edit_date"] = "2026-07-17T12:00:00+00:00"
    item_v2["content_hash"] = compute_content_hash("edited text", 500, 100)
    stats = coll.persist_items(db, src, [item_v2])
    db.commit()
    assert stats["updated"] == 1
    assert stats["new"] == 0

    from newsroom.storage.models import RawItem
    items = db.query(RawItem).filter_by(telegram_channel_id=500, telegram_message_id=100).all()
    assert len(items) == 1
    assert items[0].raw_data["text"] == "edited text"


# ── Forward attribution ──────────────────────────────────────

def test_forward_attribution_persisted(db):
    from newsroom.sources.telegram_adapter import compute_content_hash
    from newsroom.sources.telegram_collector import TelegramMTProtoCollector
    src, ch = _make_telegram_source(db, tg_id=600)
    coll = TelegramMTProtoCollector()

    item = {
        "type": "telegram", "source_id": src.id, "source_name": "test",
        "source_url": src.url, "telegram_channel_id": 600, "message_id": 200,
        "text": "forwarded content", "date": "2026-07-17T10:00:00+00:00",
        "forward_from_channel_id": 999, "forward_from_channel_name": "original_ch",
        "forward_from_message_id": 50, "link": "https://t.me/test/200",
        "content_hash": compute_content_hash("forwarded content", 600, 200),
    }
    coll.persist_items(db, src, [item])
    db.commit()

    from newsroom.storage.models import RawItem
    raw = db.query(RawItem).filter_by(telegram_channel_id=600, telegram_message_id=200).first()
    assert raw is not None
    assert raw.raw_data["forward_from_channel_id"] == 999
    assert raw.raw_data["forward_from_message_id"] == 50


# ── Gap records ──────────────────────────────────────────────

def test_gap_record_persisted(db):
    from newsroom.storage.models import TelegramMessageGap
    src, _ = _make_telegram_source(db, tg_id=700)
    gap = TelegramMessageGap(
        source_id=src.id, gap_start_id=100, gap_end_id=110,
        status="open", unresolved_count=11,
    )
    db.add(gap)
    db.commit()
    gaps = db.query(TelegramMessageGap).filter_by(source_id=src.id).all()
    assert len(gaps) == 1
    assert gaps[0].gap_start_id == 100
    assert gaps[0].gap_end_id == 110


# ── Health states ─────────────────────────────────────────────

def test_health_state_transitions(db):
    from newsroom.storage.models import TelegramChannel
    src, ch = _make_telegram_source(db, tg_id=800)
    ch.source_state = "degraded"
    ch.current_error = "connection timeout"
    db.commit()

    # Simulate recovery
    from newsroom.sources.telegram_adapter import compute_content_hash
    from newsroom.sources.telegram_collector import TelegramMTProtoCollector
    coll = TelegramMTProtoCollector()
    item = {
        "type": "telegram", "source_id": src.id, "source_name": "test",
        "source_url": src.url, "telegram_channel_id": 800, "message_id": 300,
        "text": "recovery", "date": "2026-07-17T10:00:00+00:00",
        "content_hash": compute_content_hash("recovery", 800, 300),
    }
    coll.persist_items(db, src, [item])
    db.commit()
    ch2 = db.query(TelegramChannel).filter_by(telegram_channel_id=800).first()
    assert ch2.source_state == "healthy"
    assert ch2.current_error is None


# ── Restart continuation ─────────────────────────────────────

def test_restart_continues_from_cursor(db):
    from newsroom.sources.telegram_adapter import compute_content_hash
    from newsroom.sources.telegram_collector import TelegramMTProtoCollector
    src, ch = _make_telegram_source(db, tg_id=900)
    ch.last_message_id = 500
    db.commit()

    # New session, new collector — should continue from 500
    coll = TelegramMTProtoCollector()
    item = {
        "type": "telegram", "source_id": src.id, "source_name": "test",
        "source_url": src.url, "telegram_channel_id": 900, "message_id": 501,
        "text": "after restart", "date": "2026-07-17T10:00:00+00:00",
        "content_hash": compute_content_hash("after restart", 900, 501),
    }
    stats = coll.persist_items(db, src, [item])
    db.commit()
    assert stats["new"] == 1
    from newsroom.storage.models import TelegramChannel
    ch2 = db.query(TelegramChannel).filter_by(telegram_channel_id=900).first()
    assert ch2.last_message_id == 501


# ── Transaction rollback ─────────────────────────────────────

def test_transaction_rollback_on_failure(db):
    from newsroom.storage.models import RawItem
    src, _ = _make_telegram_source(db, tg_id=1000)
    item = RawItem(
        source_id=src.id, raw_data={"type": "telegram", "text": "test"},
        content_hash="hash1", telegram_channel_id=1000, telegram_message_id=1,
    )
    db.add(item)
    db.flush()
    # Simulate failure — rollback
    db.rollback()
    count = db.query(RawItem).filter_by(telegram_channel_id=1000).count()
    assert count == 0
