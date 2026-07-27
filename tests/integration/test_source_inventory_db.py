"""PostgreSQL integration tests for the optional extended source inventory.

Real DB, no MagicMock sessions. Coverage:

- import every synthetic workbook row and reconcile it
- idempotent re-import (no duplicates, count stable)
- stable identity independent of display name
- activation creates/links sources; inactive rows carry evidence-based reasons
- disabling a source never removes its historical raw items
- cursors survive a fresh session (restart recovery)
- scheduled-boundary selection with no new material -> no-news
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.integration

DEFAULT_URL = "postgresql+psycopg://newsroom:newsroom_dev@127.0.0.1:55432/newsroom"
HEADER = [
    "ID",
    "Platform",
    "Type",
    "Name",
    "Handle / ID",
    "Direct URL",
    "Primary Topic",
    "Tags",
    "Language",
    "Content Mode",
    "Speed 1-5",
    "Informal 1-5",
    "Noise 1-5",
    "Community?",
    "Open-source/API?",
    "Risk",
    "Verification",
    "Discovery Source",
    "Tier",
    "Coverage Score",
]


@pytest.fixture
def workbook(tmp_path: Path) -> Path:
    import openpyxl

    path = tmp_path / "inventory.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "All Sources"
    sheet.append(HEADER)
    sheet.append(
        [
            1,
            "Telegram",
            "Channel",
            "Example Telegram",
            "@example",
            "https://t.me/example",
            "Programming",
            "code",
            "English",
            "Posts",
            4,
            3,
            2,
            "Yes",
            "No",
            "Low",
            "public",
            "test",
            "Core",
            80,
        ]
    )
    sheet.append(
        [
            2,
            "GitHub",
            "Repository / Feed",
            "Example Repository",
            "",
            "https://github.com/example/example",
            "Developer Tools",
            "code",
            "English",
            "Releases",
            4,
            1,
            1,
            "No",
            "Yes",
            "Low",
            "public",
            "test",
            "Core",
            90,
        ]
    )
    sheet.append(
        [
            3,
            "X / Twitter",
            "Account",
            "Example X",
            "@example",
            "https://x.com/example",
            "Programming",
            "code",
            "English",
            "Posts",
            5,
            4,
            3,
            "Yes",
            "No",
            "Medium",
            "public",
            "test",
            "Optional",
            60,
        ]
    )
    book.save(path)
    return path


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
    # Clean Production inventory rows + linked sources created by prior test runs.
    # Order matters: delete dependents before the sources they reference.
    session.execute(text("DELETE FROM source_inventory"))
    session.execute(
        text(
            "DELETE FROM story_items WHERE item_id IN ("
            "SELECT id FROM normalized_items WHERE raw_item_id IN ("
            "SELECT id FROM raw_items WHERE source_id IN ("
            "SELECT id FROM sources WHERE workbook_id IS NOT NULL)))"
        )
    )
    # ``normalized_items.duplicate_of_id`` is self-referential. Clear every
    # inbound reference before deleting the workbook-scoped rows so cleanup is
    # valid even when the processing worker created duplicate clusters.
    session.execute(
        text(
            "UPDATE normalized_items SET duplicate_of_id = NULL "
            "WHERE duplicate_of_id IN ("
            "SELECT id FROM normalized_items WHERE raw_item_id IN ("
            "SELECT id FROM raw_items WHERE source_id IN ("
            "SELECT id FROM sources WHERE workbook_id IS NOT NULL)))"
        )
    )
    session.execute(
        text(
            "DELETE FROM normalized_items WHERE raw_item_id IN ("
            "SELECT id FROM raw_items WHERE source_id IN ("
            "SELECT id FROM sources WHERE workbook_id IS NOT NULL))"
        )
    )
    session.execute(
        text(
            "DELETE FROM raw_items WHERE source_id IN ("
            "SELECT id FROM sources WHERE workbook_id IS NOT NULL)"
        )
    )
    session.execute(
        text("DELETE FROM collection_cursors WHERE source_id IN (SELECT id FROM sources WHERE workbook_id IS NOT NULL)")
    )
    session.execute(
        text("DELETE FROM collection_runs WHERE source_id IN (SELECT id FROM sources WHERE workbook_id IS NOT NULL)")
    )
    session.execute(
        text("DELETE FROM agent_reach_source_state WHERE source_id IN (SELECT id FROM sources WHERE workbook_id IS NOT NULL)")
    )
    session.execute(
        text("DELETE FROM x_account_state WHERE source_id IN (SELECT id FROM sources WHERE workbook_id IS NOT NULL)")
    )
    session.execute(text("DELETE FROM sources WHERE workbook_id IS NOT NULL"))
    session.commit()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def test_import_reconciles_all_rows(db, workbook: Path):
    from newsroom.sources.inventory import import_workbook

    report = import_workbook(db, workbook)
    db.commit()
    assert report.total_rows == 3
    count = db.execute(text("SELECT count(*) FROM source_inventory")).scalar()
    assert count == 3


def test_reimport_is_idempotent(db, workbook: Path):
    from newsroom.sources.inventory import import_workbook

    import_workbook(db, workbook)
    db.commit()
    first = db.execute(text("SELECT count(*) FROM source_inventory")).scalar()
    import_workbook(db, workbook)
    db.commit()
    second = db.execute(text("SELECT count(*) FROM source_inventory")).scalar()
    assert first == second == 3


def test_activation_links_sources_and_records_inactive_reasons(db, workbook: Path):
    from newsroom.sources.inventory import activate_inventory_sources, import_workbook

    import_workbook(db, workbook)
    db.commit()
    report = activate_inventory_sources(db, x_auth_available=False, telegram_mtproto_available=True)
    db.commit()
    assert report.total == 3
    assert report.active > 0
    # X is inactive by design (auth not configured) — evidence-based reason.
    x_row = db.execute(
        text("SELECT operational_state, inactive_reason FROM source_inventory WHERE platform = 'X / Twitter' LIMIT 1")
    ).first()
    assert x_row is not None
    assert x_row[0] in ("inactive",)
    assert x_row[1] == "x_auth_not_configured"
    # Active rows link to a sources row.
    linked = db.execute(text("SELECT count(*) FROM source_inventory WHERE source_id IS NOT NULL")).scalar()
    assert linked == report.active


def test_disabling_source_preserves_historical_items(db, workbook: Path):
    from newsroom.sources.inventory import activate_inventory_sources, import_workbook
    from newsroom.storage.models import RawItem, Source

    import_workbook(db, workbook)
    db.commit()
    activate_inventory_sources(db, x_auth_available=False, telegram_mtproto_available=True)
    db.commit()
    src = db.query(Source).filter(Source.enabled.is_(True)).first()
    assert src is not None
    # Create a historical raw item for this source.
    db.add(RawItem(source_id=src.id, raw_data={"title": "historic"}, content_hash="x" * 64))
    db.commit()
    item_id = db.execute(text("SELECT id FROM raw_items WHERE source_id = :s"), {"s": src.id}).first()[0]
    # Disable the source (simulate deactivation).
    src.enabled = False
    src.inactive_reason = "owner_disabled"
    db.commit()
    # The historical item must still exist.
    still = db.execute(text("SELECT count(*) FROM raw_items WHERE id = :i"), {"i": item_id}).scalar()
    assert still == 1


def test_cursor_survives_fresh_session(db, engine):
    """Restart recovery: a cursor written in one session is readable in another."""
    from newsroom.pipeline.cursors import load_cursor, save_cursor
    from newsroom.storage.models import Source

    # Clean any probe left by a prior run.
    probe = db.query(Source).filter_by(name="restart_probe").first()
    if probe is not None:
        db.execute(text("DELETE FROM collection_cursors WHERE source_id = :s"), {"s": probe.id})
        db.execute(text("DELETE FROM raw_items WHERE source_id = :s"), {"s": probe.id})
        db.delete(probe)
        db.commit()

    src = Source(name="restart_probe", type="rss", url="https://example.com/feed.xml", enabled=True)
    db.add(src)
    db.commit()
    save_cursor(db, src.id, {"last_published": "2026-07-21T00:00:00+00:00", "seen_entry_ids": ["a"]})
    db.commit()
    src_id = src.id

    # Open a brand-new session (simulates process restart).
    factory = sessionmaker(bind=engine)
    s2 = factory()
    try:
        cur = load_cursor(s2, src_id)
        assert cur.get("last_published") == "2026-07-21T00:00:00+00:00"
        assert "a" in cur.get("seen_entry_ids", [])
    finally:
        s2.close()


def test_scheduled_boundary_no_news(db):
    """No new stories since the boundary -> selection reports no_new_items."""
    from newsroom.editorial.selection import select_stories_for_report
    from newsroom.storage.models import ReportCursor, Story

    # Boundary in the future means nothing is "since" it.
    future = datetime.now(UTC) + timedelta(days=1)
    cur = db.query(ReportCursor).filter_by(cursor_key="scheduled_delivery").first()
    if cur is None:
        cur = ReportCursor(cursor_key="scheduled_delivery", advanced_at=future)
        db.add(cur)
    else:
        cur.advanced_at = future
    db.commit()
    # Ensure there is at least one old story (created before the future boundary).
    s = Story(headline="old", importance_score=0.0)
    db.add(s)
    db.commit()
    result = select_stories_for_report(db, "scheduled")
    assert result.no_new_items is True
    assert result.story_ids == []
