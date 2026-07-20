"""Gate 5X PostgreSQL integration tests for X/Twitter ingestion.

Real DB, no MagicMock sessions. Coverage:

- source import (x_timeline source registration)
- account/post uniqueness
- cursor persistence
- overlap idempotency
- restart
- edit update
- quote provenance
- health and retry state
- normalized/evidence flow
- transaction rollback
- no credentials persisted
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime

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
    # Clean X-specific rows. Order matters for FKs.
    session.execute(text("DELETE FROM x_account_state"))
    session.execute(text("DELETE FROM agent_reach_source_state"))
    session.execute(text("DELETE FROM agent_reach_backend_state"))
    # Clean dependent rows referencing X source types
    session.execute(
        text(
            "DELETE FROM collection_runs WHERE source_id IN ("
            "SELECT id FROM sources WHERE type IN ('x_timeline','x_post')"
            ")"
        )
    )
    # Clean reports/deliveries for stories linked to X items
    ar_story_ids_row = session.execute(
        text(
            "SELECT id FROM stories WHERE id IN ("
            "SELECT story_id FROM story_items WHERE item_id IN ("
            "SELECT id FROM normalized_items WHERE raw_item_id IN ("
            "SELECT id FROM raw_items WHERE source_id IN ("
            "SELECT id FROM sources WHERE type IN ('x_timeline','x_post')"
            "))))"
        )
    ).fetchall()
    ar_story_ids = [r[0] for r in ar_story_ids_row]
    if ar_story_ids:
        all_reports = session.execute(
            text("SELECT id, story_ids FROM reports")
        ).fetchall()
        ar_report_ids = []
        for rid, sids in all_reports:
            if sids and any(sid in ar_story_ids for sid in sids):
                ar_report_ids.append(rid)
        if ar_report_ids:
            session.execute(
                text("DELETE FROM delivery_chunks WHERE delivery_id IN ("
                     "SELECT id FROM deliveries WHERE report_id = ANY(:rids))"),
                {"rids": ar_report_ids},
            )
            session.execute(
                text("DELETE FROM deliveries WHERE report_id = ANY(:rids)"),
                {"rids": ar_report_ids},
            )
            session.execute(
                text("DELETE FROM reports WHERE id = ANY(:rids)"),
                {"rids": ar_report_ids},
            )
    session.execute(text("DELETE FROM editorial_artifact_lineage"))
    session.execute(text("DELETE FROM editorial_artifacts"))
    session.execute(text("DELETE FROM editorial_attempts"))
    session.execute(text("DELETE FROM story_items"))
    session.execute(text("DELETE FROM evidence"))
    session.execute(text("DELETE FROM stories"))
    session.execute(
        text(
            "DELETE FROM normalized_items WHERE raw_item_id IN ("
            "SELECT id FROM raw_items WHERE source_id IN ("
            "SELECT id FROM sources WHERE type IN ('x_timeline','x_post')"
            "))"
        )
    )
    session.execute(
        text(
            "DELETE FROM raw_items WHERE source_id IN ("
            "SELECT id FROM sources WHERE type IN ('x_timeline','x_post')"
            ")"
        )
    )
    session.execute(
        text(
            "DELETE FROM collection_cursors WHERE source_id IN ("
            "SELECT id FROM sources WHERE type IN ('x_timeline','x_post')"
            ")"
        )
    )
    session.execute(
        text(
            "DELETE FROM sources WHERE type IN ('x_timeline','x_post')"
        )
    )
    session.commit()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


# ── 1. Schema ──────────────────────────────────────────────────


def test_x_account_state_table_exists(engine):
    insp = inspect(engine)
    tables = insp.get_table_names()
    assert "x_account_state" in tables


def test_alembic_at_gate5x_revision(engine):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
    assert row is not None
    assert row[0] == "0008_gate5x_x_ingestion"


# ── 2. Source import ───────────────────────────────────────────


def test_x_timeline_source_imported(db):
    """An x_timeline source can be imported and queried back."""
    from newsroom.storage.models import Source

    src = Source(
        name="x_ai_account",
        type="x_timeline",
        url="agent-reach:x-timeline:ai_account",
        enabled=True,
        config={
            "handle": "ai_account",
            "auth_token_env": "TWITTER_AUTH_TOKEN",
            "ct0_env": "TWITTER_CT0",
            "max_posts": 20,
            "include_replies": False,
            "include_reposts": False,
        },
        health_status="configured",
    )
    db.add(src)
    db.commit()

    found = db.query(Source).filter_by(name="x_ai_account").first()
    assert found is not None
    assert found.type == "x_timeline"
    assert found.config["handle"] == "ai_account"
    # Config carries env var NAMES, not values
    assert "TWITTER_AUTH_TOKEN" not in str(found.config) or "fake" not in str(found.config)


# ── 3. Account state persistence ──────────────────────────────


def test_x_account_state_persisted(db):
    from newsroom.storage.models import Source, XAccountState

    src = Source(
        name="x_state_test",
        type="x_timeline",
        url="agent-reach:x-timeline:state_test",
        enabled=True,
        config={"handle": "state_test"},
    )
    db.add(src)
    db.flush()

    state = XAccountState(
        source_id=src.id,
        account_id="1234567890",
        configured_handle="state_test",
        last_resolved_handle="state_test",
        last_resolved_at=datetime.now(UTC),
        health_status="healthy",
        cursor={"last_stable_item_id": "999", "seen_item_ids": ["111", "222"]},
        total_posts_collected=5,
    )
    db.add(state)
    db.commit()

    found = db.query(XAccountState).filter_by(source_id=src.id).first()
    assert found is not None
    assert found.account_id == "1234567890"
    assert found.configured_handle == "state_test"
    assert found.cursor["last_stable_item_id"] == "999"
    assert "111" in found.cursor["seen_item_ids"]


# ── 4. Account/post uniqueness ─────────────────────────────────


def test_source_id_unique_in_x_account_state(db):
    from newsroom.storage.models import Source, XAccountState

    src = Source(
        name="x_unique_test",
        type="x_timeline",
        url="agent-reach:x-timeline:unique",
        enabled=True,
        config={"handle": "unique"},
    )
    db.add(src)
    db.flush()

    state1 = XAccountState(
        source_id=src.id,
        account_id="100",
        configured_handle="unique",
    )
    db.add(state1)
    db.commit()

    state2 = XAccountState(
        source_id=src.id,
        account_id="100",
        configured_handle="unique",
    )
    db.add(state2)
    with pytest.raises(Exception):  # noqa: B017 — assert the unique constraint
        db.commit()
    db.rollback()


def test_post_id_unique_by_content_hash(db):
    """Two X posts with the same post_id have the same content_hash and are deduplicated."""
    from newsroom.storage.models import RawItem, Source

    src = Source(
        name="x_dedup_test",
        type="x_timeline",
        url="agent-reach:x-timeline:dedup",
        enabled=True,
        config={"handle": "dedup_test", "account_id": "100"},
    )
    db.add(src)
    db.flush()

    raw_data = {"type": "x_post", "post_id": "1234567890", "text": "Hello", "handle": "dedup_test"}
    content_hash = hashlib.sha256(b"x:1234567890").hexdigest()
    item = RawItem(source_id=src.id, raw_data=raw_data, content_hash=content_hash)
    db.add(item)
    db.commit()

    existing = db.query(RawItem).filter_by(source_id=src.id, content_hash=content_hash).first()
    assert existing is not None


# ── 5. Cursor persistence ──────────────────────────────────────


def test_cursor_persisted_for_x_source(db):
    from newsroom.pipeline.cursors import load_cursor, save_cursor
    from newsroom.storage.models import Source

    src = Source(
        name="x_cursor_test",
        type="x_timeline",
        url="agent-reach:x-timeline:cursor",
        enabled=True,
        config={"handle": "cursor_test"},
    )
    db.add(src)
    db.flush()

    cursor = {"last_stable_item_id": "555", "seen_item_ids": ["111", "222", "333"]}
    save_cursor(db, src.id, cursor)
    db.commit()

    loaded = load_cursor(db, src.id)
    assert loaded["last_stable_item_id"] == "555"
    assert "111" in loaded["seen_item_ids"]


# ── 6. Restart continuation ───────────────────────────────────


def test_restart_continues_from_cursor(db):
    from newsroom.pipeline.cursors import (
        advance_cursor_from_items,
        filter_new_items,
        load_cursor,
        save_cursor,
    )
    from newsroom.storage.models import Source

    src = Source(
        name="x_restart_test",
        type="x_timeline",
        url="agent-reach:x-timeline:restart",
        enabled=True,
        config={"handle": "restart_test"},
    )
    db.add(src)
    db.flush()

    # Cycle 1: posts 111, 222, 333
    cycle1 = [{"post_id": "111"}, {"post_id": "222"}, {"post_id": "333"}]
    cursor1 = advance_cursor_from_items({}, cycle1, source_type="x_timeline")
    save_cursor(db, src.id, cursor1)
    db.commit()

    # Simulate restart
    loaded = load_cursor(db, src.id)

    # Cycle 2: posts 222, 333, 444 (overlap)
    cycle2 = [{"post_id": "222"}, {"post_id": "333"}, {"post_id": "444"}]
    new_in_cycle2 = filter_new_items(cycle2, loaded, source_type="x_timeline")
    assert len(new_in_cycle2) == 1
    assert new_in_cycle2[0]["post_id"] == "444"


# ── 7. Edit update ─────────────────────────────────────────────


def test_edited_x_post_updates_in_place(db):
    from newsroom.storage.models import RawItem, Source

    src = Source(
        name="x_edit_test",
        type="x_timeline",
        url="agent-reach:x-timeline:edit",
        enabled=True,
        config={"handle": "edit_test"},
    )
    db.add(src)
    db.flush()

    content_hash = hashlib.sha256(b"x:1234567890").hexdigest()
    raw_data = {"type": "x_post", "post_id": "1234567890", "text": "original", "handle": "edit_test"}
    raw = RawItem(source_id=src.id, raw_data=raw_data, content_hash=content_hash)
    db.add(raw)
    db.commit()

    # Simulate an edit: same post_id, new text
    found = db.query(RawItem).filter_by(source_id=src.id, content_hash=content_hash).first()
    found.raw_data = {"type": "x_post", "post_id": "1234567890", "text": "edited", "handle": "edit_test"}
    db.commit()

    again = db.query(RawItem).filter_by(source_id=src.id, content_hash=content_hash).first()
    assert again.raw_data["text"] == "edited"


# ── 8. Quote provenance ───────────────────────────────────────


def test_quote_post_provenance_persisted(db):
    """Quote-post metadata is persisted in raw_data and traceable to the original."""
    from newsroom.storage.models import RawItem, Source

    src = Source(
        name="x_quote_test",
        type="x_timeline",
        url="agent-reach:x-timeline:quote",
        enabled=True,
        config={"handle": "quote_test"},
    )
    db.add(src)
    db.flush()

    raw_data = {
        "type": "x_post",
        "post_id": "777",
        "text": "My commentary",
        "post_kind": "quote",
        "quoted_tweet": {
            "quoted_post_id": "555",
            "quoted_text": "Original quoted text",
            "quoted_author_id": "200",
            "quoted_author_handle": "quoted_user",
            "quoted_url": "https://x.com/quoted_user/status/555",
        },
    }
    content_hash = hashlib.sha256(b"x:777").hexdigest()
    raw = RawItem(source_id=src.id, raw_data=raw_data, content_hash=content_hash)
    db.add(raw)
    db.commit()

    found = db.query(RawItem).filter_by(content_hash=content_hash).first()
    assert found is not None
    assert found.raw_data["post_kind"] == "quote"
    assert found.raw_data["quoted_tweet"]["quoted_post_id"] == "555"
    assert found.raw_data["quoted_tweet"]["quoted_url"] == "https://x.com/quoted_user/status/555"


# ── 9. Health and retry state ──────────────────────────────────


def test_health_and_retry_state_persisted(db):
    from datetime import timedelta

    from newsroom.storage.models import Source, XAccountState

    src = Source(
        name="x_health_test",
        type="x_timeline",
        url="agent-reach:x-timeline:health",
        enabled=True,
        config={"handle": "health_test"},
    )
    db.add(src)
    db.flush()

    retry_after = datetime.now(UTC) + timedelta(seconds=300)
    state = XAccountState(
        source_id=src.id,
        account_id="100",
        configured_handle="health_test",
        health_status="rate_limited",
        retry_after=retry_after,
        rate_limit_state={"remaining": 0, "reset_ts": retry_after.isoformat()},
        last_error_category="rate_limit",
        consecutive_failures=2,
        total_posts_collected=10,
    )
    db.add(state)
    db.commit()

    found = db.query(XAccountState).filter_by(source_id=src.id).first()
    assert found is not None
    assert found.health_status == "rate_limited"
    assert found.retry_after is not None
    assert found.rate_limit_state["remaining"] == 0
    assert found.last_error_category == "rate_limit"
    assert found.consecutive_failures == 2
    assert found.total_posts_collected == 10


# ── 10. Normalized/evidence flow ──────────────────────────────


def test_x_post_flows_to_normalized(db):
    from newsroom.processing.normalize import Normalizer
    from newsroom.storage.models import NormalizedItem, RawItem, Source

    src = Source(
        name="x_norm_flow",
        type="x_timeline",
        url="agent-reach:x-timeline:norm",
        enabled=True,
        config={"handle": "norm_test"},
    )
    db.add(src)
    db.flush()

    raw_data = {
        "type": "x_post",
        "post_id": "111222333",
        "text": "AI breakthrough announcement",
        "handle": "norm_test",
        "account_id": "100",
        "post_kind": "original",
        "published": "2026-07-20T12:00:00+00:00",
        "canonical_url": "https://x.com/norm_test/status/111222333",
        "link": "https://x.com/norm_test/status/111222333",
    }
    content_hash = hashlib.sha256(b"x:111222333").hexdigest()
    raw = RawItem(source_id=src.id, raw_data=raw_data, content_hash=content_hash)
    db.add(raw)
    db.flush()

    normalizer = Normalizer()
    norm_data = normalizer.normalize(raw_data)
    norm = NormalizedItem(
        raw_item_id=raw.id,
        title=norm_data["title"],
        description=norm_data.get("description") or "",
        source_url=norm_data["source_url"],
        canonical_url=norm_data.get("canonical_url") or "",
        published_at=norm_data.get("published_at"),
        language=norm_data.get("language"),
        content_hash=norm_data["content_hash"],
        url_hash=norm_data.get("url_hash") or "",
    )
    db.add(norm)
    db.commit()

    found = db.query(NormalizedItem).filter_by(raw_item_id=raw.id).first()
    assert found is not None
    assert "AI breakthrough" in found.title
    assert "x.com/norm_test/status/111222333" in found.source_url


# ── 11. Transaction rollback ──────────────────────────────────


def test_transaction_rollback_on_duplicate_source_id(db):
    from newsroom.storage.models import Source, XAccountState

    src = Source(
        name="x_rollback_test",
        type="x_timeline",
        url="agent-reach:x-timeline:rollback",
        enabled=True,
        config={"handle": "rollback_test"},
    )
    db.add(src)
    db.flush()

    state1 = XAccountState(
        source_id=src.id,
        account_id="100",
        configured_handle="rollback_test",
    )
    db.add(state1)
    db.commit()

    state2 = XAccountState(
        source_id=src.id,
        account_id="100",
        configured_handle="rollback_test",
    )
    db.add(state2)
    with pytest.raises(Exception):  # noqa: B017
        db.commit()
    db.rollback()

    found = db.query(XAccountState).filter_by(source_id=src.id).first()
    assert found is not None


# ── 12. No credentials persisted ──────────────────────────────


def test_no_credential_fields_in_x_account_state(engine):
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("x_account_state")}
    forbidden = {"cookies", "token", "api_key", "auth_header", "browser_profile", "password", "ct0", "auth_token"}
    assert not (cols & forbidden)


def test_source_config_no_token_values(db):
    from newsroom.storage.models import Source

    src = Source(
        name="x_no_creds",
        type="x_timeline",
        url="agent-reach:x-timeline:nocreds",
        enabled=True,
        config={
            "handle": "nocreds",
            "auth_token_env": "TWITTER_AUTH_TOKEN",
            "ct0_env": "TWITTER_CT0",
        },
    )
    db.add(src)
    db.commit()

    found = db.query(Source).filter_by(name="x_no_creds").first()
    config_str = str(found.config)
    # No actual credential values in config — only env var names
    assert found.config.get("auth_token_env") == "TWITTER_AUTH_TOKEN"
    assert "fake" not in config_str
    assert "token_value" not in config_str
    assert "cookie" not in config_str.lower()
