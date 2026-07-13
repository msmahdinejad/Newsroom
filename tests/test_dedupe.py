"""Test deduplication pipeline."""

import pytest

from newsroom.processing.dedupe import Deduplicator
from newsroom.storage.models import NormalizedItem, RawItem, Source


@pytest.fixture
def sample_source(db_session):
    """Create a test source."""
    source = Source(
        name="Test Source",
        type="rss",
        url="https://example.com/feed",
    )
    db_session.add(source)
    db_session.commit()
    return source


@pytest.fixture
def deduplicator():
    """Create deduplicator instance."""
    return Deduplicator()


def test_deduplicate_exact_hash_match(db_session, sample_source, deduplicator):
    """Test marking duplicates with exact hash match."""
    # Create two raw items
    raw1 = RawItem(source_id=sample_source.id, raw_data='{"title":"Article"}')
    raw2 = RawItem(source_id=sample_source.id, raw_data='{"title":"Article"}')
    db_session.add_all([raw1, raw2])
    db_session.commit()

    # Create normalized items with same hash
    item1 = NormalizedItem(
        raw_item_id=raw1.id,
        title="Same Article",
        source_url="https://example.com/1",
        content_hash="abc123",
        normalized_url="https://example.com/1",
    )
    item2 = NormalizedItem(
        raw_item_id=raw2.id,
        title="Same Article",
        source_url="https://example.com/2",
        content_hash="abc123",  # Same hash
        normalized_url="https://example.com/2",
    )
    db_session.add_all([item1, item2])
    db_session.commit()

    # Run deduplication
    stats = deduplicator.deduplicate_batch([item1.id, item2.id])

    # Verify
    db_session.refresh(item1)
    db_session.refresh(item2)

    assert item1.is_duplicate is False  # Older item is not marked
    assert item2.is_duplicate is True  # Newer item marked
    assert item2.duplicate_of_id == item1.id
    assert stats["duplicates_marked"] == 1


def test_deduplicate_url_match(db_session, sample_source, deduplicator):
    """Test marking duplicates with normalized URL match."""
    raw1 = RawItem(source_id=sample_source.id, raw_data='{"url":"https://example.com"}')
    raw2 = RawItem(source_id=sample_source.id, raw_data='{"url":"https://example.com?utm=1"}')
    db_session.add_all([raw1, raw2])
    db_session.commit()

    item1 = NormalizedItem(
        raw_item_id=raw1.id,
        title="Article A",
        source_url="https://example.com/article",
        content_hash="hash1",
        normalized_url="https://example.com/article",
    )
    item2 = NormalizedItem(
        raw_item_id=raw2.id,
        title="Article B",
        source_url="https://example.com/article?utm_source=twitter",
        content_hash="hash2",  # Different hash
        normalized_url="https://example.com/article",  # Same normalized URL
    )
    db_session.add_all([item1, item2])
    db_session.commit()

    stats = deduplicator.deduplicate_batch([item1.id, item2.id])

    db_session.refresh(item1)
    db_session.refresh(item2)

    assert item1.is_duplicate is False
    assert item2.is_duplicate is True
    assert item2.duplicate_of_id == item1.id
    assert stats["duplicates_marked"] == 1


def test_deduplicate_no_duplicates(db_session, sample_source, deduplicator):
    """Test deduplication with no duplicates."""
    raw1 = RawItem(source_id=sample_source.id, raw_data='{"a":1}')
    raw2 = RawItem(source_id=sample_source.id, raw_data='{"b":2}')
    db_session.add_all([raw1, raw2])
    db_session.commit()

    item1 = NormalizedItem(
        raw_item_id=raw1.id,
        title="Article A",
        source_url="https://example.com/a",
        content_hash="hash_a",
        normalized_url="https://example.com/a",
    )
    item2 = NormalizedItem(
        raw_item_id=raw2.id,
        title="Article B",
        source_url="https://example.com/b",
        content_hash="hash_b",
        normalized_url="https://example.com/b",
    )
    db_session.add_all([item1, item2])
    db_session.commit()

    stats = deduplicator.deduplicate_batch([item1.id, item2.id])

    db_session.refresh(item1)
    db_session.refresh(item2)

    assert item1.is_duplicate is False
    assert item2.is_duplicate is False
    assert stats["duplicates_marked"] == 0


def test_get_duplicate_chain(db_session, sample_source, deduplicator):
    """Test retrieving duplicate chain."""
    # Create chain: item1 <- item2 <- item3
    raw1 = RawItem(source_id=sample_source.id, raw_data='{"i":1}')
    raw2 = RawItem(source_id=sample_source.id, raw_data='{"i":2}')
    raw3 = RawItem(source_id=sample_source.id, raw_data='{"i":3}')
    db_session.add_all([raw1, raw2, raw3])
    db_session.commit()

    item1 = NormalizedItem(
        raw_item_id=raw1.id,
        title="Root",
        source_url="https://example.com/root",
        content_hash="same_hash",
        normalized_url="https://example.com/root",
    )
    db_session.add(item1)
    db_session.commit()

    item2 = NormalizedItem(
        raw_item_id=raw2.id,
        title="Dup 1",
        source_url="https://example.com/dup1",
        content_hash="same_hash",
        normalized_url="https://example.com/dup1",
        is_duplicate=True,
        duplicate_of_id=item1.id,
    )
    item3 = NormalizedItem(
        raw_item_id=raw3.id,
        title="Dup 2",
        source_url="https://example.com/dup2",
        content_hash="same_hash",
        normalized_url="https://example.com/dup2",
        is_duplicate=True,
        duplicate_of_id=item1.id,
    )
    db_session.add_all([item2, item3])
    db_session.commit()

    # Get chain from any item
    chain = deduplicator.get_duplicate_chain(item2.id)

    assert len(chain) == 3
    assert chain[0] == item1.id  # Root first
    assert item2.id in chain
    assert item3.id in chain


def test_empty_url_not_matched(db_session, sample_source, deduplicator):
    """Test items with empty URLs are not matched."""
    raw1 = RawItem(source_id=sample_source.id, raw_data='{}')
    raw2 = RawItem(source_id=sample_source.id, raw_data='{}')
    db_session.add_all([raw1, raw2])
    db_session.commit()

    item1 = NormalizedItem(
        raw_item_id=raw1.id,
        title="No URL 1",
        source_url="",
        content_hash="hash1",
        normalized_url="",
    )
    item2 = NormalizedItem(
        raw_item_id=raw2.id,
        title="No URL 2",
        source_url="",
        content_hash="hash2",
        normalized_url="",  # Both empty, should not match by URL
    )
    db_session.add_all([item1, item2])
    db_session.commit()

    stats = deduplicator.deduplicate_batch([item1.id, item2.id])

    db_session.refresh(item1)
    db_session.refresh(item2)

    assert item1.is_duplicate is False
    assert item2.is_duplicate is False
