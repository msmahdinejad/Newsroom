"""Test story clustering."""

import json

import pytest

from newsroom.processing.cluster import Clusterer
from newsroom.storage.models import NormalizedItem, RawItem, Source, Story


@pytest.fixture
def sample_source(db_session):
    """Create test source."""
    source = Source(name="Test", type="rss", url="https://example.com")
    db_session.add(source)
    db_session.commit()
    return source


@pytest.fixture
def clusterer():
    """Create clusterer instance."""
    return Clusterer()


def test_cluster_similar_items(db_session, sample_source, clusterer):
    """Test clustering items with similar keywords."""
    # Create items about Python
    raw1 = RawItem(source_id=sample_source.id, raw_data='{}')
    raw2 = RawItem(source_id=sample_source.id, raw_data='{}')
    db_session.add_all([raw1, raw2])
    db_session.commit()

    item1 = NormalizedItem(
        raw_item_id=raw1.id,
        title="Python 3.13 Released",
        description="New Python version with performance improvements",
        source_url="https://python.org/1",
        content_hash="hash1",
        normalized_url="https://python.org/1",
    )
    item2 = NormalizedItem(
        raw_item_id=raw2.id,
        title="Python 3.13 Performance Boost",
        description="Python 3.13 brings major speed improvements",
        source_url="https://example.com/2",
        content_hash="hash2",
        normalized_url="https://example.com/2",
    )
    db_session.add_all([item1, item2])
    db_session.commit()

    stats = clusterer.cluster_items([item1.id, item2.id])

    assert stats["stories_created"] == 1  # Grouped into one story
    assert stats["items_clustered"] == 2

    story = db_session.query(Story).first()
    assert story is not None
    assert "python" in story.headline.lower()

    item_ids = eval(story.item_ids)  # noqa: S307
    assert item1.id in item_ids
    assert item2.id in item_ids


def test_cluster_dissimilar_items(db_session, sample_source, clusterer):
    """Test clustering items with no keyword overlap."""
    raw1 = RawItem(source_id=sample_source.id, raw_data='{}')
    raw2 = RawItem(source_id=sample_source.id, raw_data='{}')
    db_session.add_all([raw1, raw2])
    db_session.commit()

    item1 = NormalizedItem(
        raw_item_id=raw1.id,
        title="Python Framework Django Released",
        description="Django 5.0 now available",
        source_url="https://example.com/1",
        content_hash="hash1",
        normalized_url="https://example.com/1",
    )
    item2 = NormalizedItem(
        raw_item_id=raw2.id,
        title="JavaScript Library React Updated",
        description="React 19 brings new features",
        source_url="https://example.com/2",
        content_hash="hash2",
        normalized_url="https://example.com/2",
    )
    db_session.add_all([item1, item2])
    db_session.commit()

    stats = clusterer.cluster_items([item1.id, item2.id])

    assert stats["stories_created"] == 2  # Two separate stories
    assert stats["items_clustered"] == 2


def test_extract_keywords(clusterer):
    """Test keyword extraction."""
    text = "Python 3.13 Released with Performance Improvements"
    keywords = clusterer._extract_keywords(text)

    assert "python" in keywords
    assert "released" in keywords
    assert "performance" in keywords
    assert "improvements" in keywords

    # Stopwords filtered
    assert "with" not in keywords


def test_compute_similarity(clusterer):
    """Test Jaccard similarity computation."""
    set1 = {"python", "release", "performance"}
    set2 = {"python", "release", "speed"}

    similarity = clusterer._compute_similarity(set1, set2)

    # Intersection: 2, Union: 4, Similarity: 0.5
    assert similarity == 0.5


def test_compute_similarity_no_overlap(clusterer):
    """Test similarity with no overlap."""
    set1 = {"python", "django"}
    set2 = {"javascript", "react"}

    similarity = clusterer._compute_similarity(set1, set2)

    assert similarity == 0.0


def test_compute_similarity_empty_sets(clusterer):
    """Test similarity with empty sets."""
    assert clusterer._compute_similarity(set(), {"word"}) == 0.0
    assert clusterer._compute_similarity({"word"}, set()) == 0.0


def test_skip_duplicate_items(db_session, sample_source, clusterer):
    """Test that duplicate items are not clustered."""
    raw1 = RawItem(source_id=sample_source.id, raw_data='{}')
    raw2 = RawItem(source_id=sample_source.id, raw_data='{}')
    db_session.add_all([raw1, raw2])
    db_session.commit()

    item1 = NormalizedItem(
        raw_item_id=raw1.id,
        title="Original Item",
        source_url="https://example.com/1",
        content_hash="hash1",
        normalized_url="https://example.com/1",
    )
    item2 = NormalizedItem(
        raw_item_id=raw2.id,
        title="Duplicate Item",
        source_url="https://example.com/2",
        content_hash="hash1",
        normalized_url="https://example.com/2",
        is_duplicate=True,
        duplicate_of_id=item1.id,
    )
    db_session.add_all([item1, item2])
    db_session.commit()

    stats = clusterer.cluster_items([item1.id, item2.id])

    # Only non-duplicate item clustered
    assert stats["items_clustered"] == 1

    story = db_session.query(Story).first()
    item_ids = eval(story.item_ids)  # noqa: S307
    assert len(item_ids) == 1
    assert item1.id in item_ids
    assert item2.id not in item_ids
