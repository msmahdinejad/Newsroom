"""Regression tests for safe legacy cluster partitioning."""

from __future__ import annotations

from newsroom.processing.cluster_repair import partition_story_items
from newsroom.storage.models import NormalizedItem


def _item(item_id: int, title: str, description: str = "") -> NormalizedItem:
    return NormalizedItem(
        id=item_id,
        raw_item_id=item_id,
        title=title,
        description=description,
        source_url=f"https://example.test/{item_id}",
        content_hash=f"hash-{item_id}",
    )


def test_partition_splits_unrelated_reddit_html_posts():
    items = [
        _item(
            1,
            '<a href="https://reddit.com/a">Python 3.13 runtime released</a>',
            "submitted by user",
        ),
        _item(
            2,
            '<a href="https://reddit.com/b">Rust database client released</a>',
            "submitted by user",
        ),
    ]

    partitions = partition_story_items(items)

    assert [[item.id for item in group] for group in partitions] == [[1], [2]]


def test_partition_keeps_genuinely_related_release_reports_together():
    items = [
        _item(1, "Python 3.13 runtime released with free-threaded mode"),
        _item(2, "Python 3.13 release adds free-threaded runtime"),
    ]

    partitions = partition_story_items(items)

    assert [[item.id for item in group] for group in partitions] == [[1, 2]]
