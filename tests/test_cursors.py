"""Unit tests for cursor filter/advance logic (DB-free, pure functions)."""

from newsroom.pipeline.cursors import advance_cursor_from_items, filter_new_items


def test_first_collection_empty_cursor_returns_all():
    items = [{"entry_id": "1", "published": "2026-07-14T10:00:00+00:00"}]
    assert filter_new_items(items, {}, source_type="rss") == items


def test_rss_drops_older_items_keeps_overlap():
    cursor = {"last_published": "2026-07-14T10:00:00+00:00", "seen_entry_ids": ["1"]}
    items = [
        {"entry_id": "1", "published": "2026-07-14T10:00:00+00:00"},  # seen, overlap
        {"entry_id": "2", "published": "2026-07-14T11:00:00+00:00"},  # new
        {"entry_id": "3", "published": "2026-07-14T09:00:00+00:00"},  # older
    ]
    out = filter_new_items(items, cursor, source_type="rss")
    ids = [i["entry_id"] for i in out]
    assert "3" not in ids  # older dropped
    assert "2" in ids
    # seen id may be kept for overlap dedup, that's ok


def test_github_drops_lower_release_ids():
    cursor = {"last_release_id": 100}
    items = [
        {"release_id": 99},
        {"release_id": 100},  # equal, overlap
        {"release_id": 101},
    ]
    out = filter_new_items(items, cursor, source_type="github_releases")
    rids = [i["release_id"] for i in out]
    assert 99 not in rids
    assert 101 in rids


def test_advance_rss_uses_max_published():
    cursor = {"last_published": "2026-07-14T10:00:00+00:00", "seen_entry_ids": ["1"]}
    persisted = [
        {"entry_id": "2", "published": "2026-07-14T11:00:00+00:00"},
        {"entry_id": "1", "published": "2026-07-14T10:00:00+00:00"},
    ]
    next_c = advance_cursor_from_items(cursor, persisted, source_type="rss")
    assert next_c["last_published"] == "2026-07-14T11:00:00+00:00"
    assert "2" in next_c["seen_entry_ids"]


def test_advance_github_uses_max_release_id():
    cursor = {"last_release_id": 100}
    persisted = [{"release_id": 105}, {"release_id": 101}]
    next_c = advance_cursor_from_items(cursor, persisted, source_type="github_releases")
    assert next_c["last_release_id"] == "105"


def test_advance_no_items_keeps_cursor():
    cursor = {"last_published": "2026-07-14T10:00:00+00:00"}
    next_c = advance_cursor_from_items(cursor, [], source_type="rss")
    assert next_c == cursor
