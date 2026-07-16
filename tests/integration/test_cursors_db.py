"""Collection cursor persistence against real PostgreSQL."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from newsroom.pipeline.cursors import (
    advance_cursor_from_items,
    filter_new_items,
    load_cursor,
    save_cursor,
)
from newsroom.storage.models import CollectionCursor, Source

pytestmark = pytest.mark.integration

SRC_NAME = "__gate1_cursor_source__"


@pytest.fixture
def source(db: Session) -> Source:
    s = db.query(Source).filter_by(name=SRC_NAME).first()
    if not s:
        s = Source(name=SRC_NAME, type="rss", url="https://example.com/cursor.xml")
        db.add(s)
        db.commit()
        db.refresh(s)
    # clear cursors
    db.query(CollectionCursor).filter_by(source_id=s.id).delete()
    db.commit()
    return s


def test_first_and_incremental_cursor(db: Session, source: Source) -> None:
    assert load_cursor(db, source.id) == {}
    items1 = [
        {"entry_id": "a", "published": "2026-07-14T10:00:00+00:00"},
        {"entry_id": "b", "published": "2026-07-14T11:00:00+00:00"},
    ]
    c1 = advance_cursor_from_items({}, items1, source_type="rss")
    save_cursor(db, source.id, c1)
    db.commit()

    loaded = load_cursor(db, source.id)
    assert loaded["last_published"] == "2026-07-14T11:00:00+00:00"
    assert "b" in loaded["seen_entry_ids"]

    # second collection: only newer
    items2 = [
        {"entry_id": "b", "published": "2026-07-14T11:00:00+00:00"},
        {"entry_id": "c", "published": "2026-07-14T12:00:00+00:00"},
        {"entry_id": "old", "published": "2026-07-14T09:00:00+00:00"},
    ]
    filtered = filter_new_items(items2, loaded, source_type="rss")
    ids = [i["entry_id"] for i in filtered]
    assert "old" not in ids
    assert "c" in ids


def test_cursor_not_advanced_on_empty_persist(db: Session, source: Source) -> None:
    save_cursor(db, source.id, {"last_published": "2026-07-14T10:00:00+00:00"})
    db.commit()
    before = load_cursor(db, source.id)
    after = advance_cursor_from_items(before, [], source_type="rss")
    assert after == before


def test_github_cursor_roundtrip(db: Session) -> None:
    name = "__gate1_gh_cursor__"
    s = db.query(Source).filter_by(name=name).first()
    if not s:
        s = Source(name=name, type="github_releases", url="https://github.com/o/r")
        db.add(s)
        db.commit()
        db.refresh(s)
    db.query(CollectionCursor).filter_by(source_id=s.id).delete()
    db.commit()
    c = advance_cursor_from_items({}, [{"release_id": 10}, {"release_id": 20}], source_type="github_releases")
    save_cursor(db, s.id, c)
    db.commit()
    loaded = load_cursor(db, s.id)
    assert int(loaded["last_release_id"]) == 20
