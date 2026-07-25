"""Test evidence packet construction from stories."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from newsroom.processing.evidence import EvidenceBuilder
from newsroom.storage.models import Story


@pytest.fixture
def builder():
    return EvidenceBuilder()


@pytest.fixture
def story():
    """A minimal Story."""
    return Story(
        id=1,
        headline="Python 3.13 Released",
        summary="",
        trust_status="confirmed",
        confidence=0.9,
        importance_score=0.8,
        cluster_keywords=["python", "3.13", "release"],
        source_count=2,
    )


def _make_item(item_id, title, description="", source_name="TestSource", source_type="rss"):
    """Create a mock NormalizedItem with nested raw_item.source."""
    item = MagicMock()
    item.id = item_id
    item.title = title
    item.description = description
    item.source_url = "https://example.com/article"
    item.canonical_url = "https://example.com/article"
    item.published_at = datetime(2026, 7, 13, 10, 0, tzinfo=UTC)
    item.language = "en"
    # raw_item → source chain
    item.raw_item = MagicMock()
    item.raw_item.source = MagicMock()
    item.raw_item.source.name = source_name
    item.raw_item.source.type = source_type
    return item


# ── Packet construction ─────────────────────────────────────────

def test_build_packet_has_required_fields(builder, story):
    items = [_make_item(1, "Python 3.13 Released", "Description here")]
    packet = builder._build_packet(story, items)

    assert packet["story_id"] == 1
    assert packet["headline"] == "Python 3.13 Released"
    assert packet["keywords"] == ["python", "3.13", "release"]
    assert packet["trust_status"] == "confirmed"
    assert packet["confidence"] == 0.9
    assert packet["importance_score"] == 0.8
    assert packet["source_count"] == 2
    assert packet["item_count"] == 1
    assert packet["contradictions"] == []
    assert isinstance(packet["sources"], list)
    assert isinstance(packet["facts"], list)


def test_build_packet_sources(builder, story):
    items = [
        _make_item(1, "Title A", "Desc A", "SourceOne", "rss"),
        _make_item(2, "Title B", "Desc B", "SourceTwo", "github_releases"),
    ]
    packet = builder._build_packet(story, items)

    assert len(packet["sources"]) == 2
    s = packet["sources"][0]
    assert s["name"] == "SourceOne"
    assert s["type"] == "rss"
    assert s["url"] == "https://example.com/article"
    assert s["title"] == "Title A"
    assert s["excerpt"] == "Desc A"
    assert s["language"] == "en"
    assert s["published_at"] is not None


def test_build_packet_source_excerpt_truncated(builder, story):
    """Excerpt is capped at 300 chars."""
    long_desc = "x" * 500
    items = [_make_item(1, "Title", long_desc)]
    packet = builder._build_packet(story, items)
    assert len(packet["sources"][0]["excerpt"]) == 300


def test_build_packet_source_title_truncated(builder, story):
    """Title in source is capped at 200 chars."""
    long_title = "T" * 300
    items = [_make_item(1, long_title)]
    packet = builder._build_packet(story, items)
    assert len(packet["sources"][0]["title"]) == 200


def test_build_packet_handles_no_source(builder, story):
    """Item with no raw_item/source → source name empty, type unknown."""
    item = MagicMock()
    item.id = 1
    item.title = "Orphan"
    item.description = "desc"
    item.source_url = ""
    item.canonical_url = ""
    item.published_at = None
    item.language = "en"
    item.raw_item = None

    packet = builder._build_packet(story, [item])
    assert packet["sources"][0]["name"] == ""
    assert packet["sources"][0]["type"] == "unknown"


# ── Fact extraction ─────────────────────────────────────────────

def test_extract_facts_from_titles(builder):
    items = [
        _make_item(1, "Python 3.13 Released"),
        _make_item(2, "Python 3.13 Released"),  # duplicate title → skipped
    ]
    facts = builder._extract_facts(items)
    # Only unique titles
    assert len(facts) == 1
    assert facts[0] == "Python 3.13 Released"


def test_extract_facts_from_description_first_sentence(builder):
    items = [_make_item(1, "Title", "This is the first sentence here. Second one.")]
    facts = builder._extract_facts(items)
    assert "Title" in facts
    assert "This is the first sentence here" in facts  # len > 20


def test_extract_facts_dedup(builder):
    """Same text in title and description first-sentence → only one entry."""
    items = [_make_item(1, "Same text", "Same text. More.")]
    facts = builder._extract_facts(items)
    assert facts.count("Same text") == 1


def test_extract_facts_bounded_to_10(builder):
    """Facts list capped at 10."""
    items = [_make_item(i, f"Unique title {i}", f"Desc {i}.") for i in range(20)]
    facts = builder._extract_facts(items)
    assert len(facts) <= 10


def test_extract_facts_short_description_skipped(builder):
    """Description first-sentence ≤20 chars → skipped."""
    items = [_make_item(1, "Good Title", "Short. More.")]
    facts = builder._extract_facts(items)
    assert "Good Title" in facts
    assert "Short" not in facts  # len("Short") = 5 ≤ 20


# ── build_for_story with mock DB ─────────────────────────────────

def test_build_for_story_persists_evidence(builder, story, mock_db):
    """build_for_story creates Evidence and returns its ID."""
    items = [_make_item(1, "Python 3.13 Released", "Description")]
    items_query = MagicMock()
    items_query.join.return_value = items_query
    items_query.filter.return_value = items_query
    items_query.all.return_value = items
    evidence_query = MagicMock()
    evidence_query.filter_by.return_value = evidence_query
    evidence_query.order_by.return_value = evidence_query
    evidence_query.first.return_value = None
    mock_db.query.side_effect = [items_query, evidence_query]

    # db.flush() should set an id on the Evidence
    def flush_side_effect():
        for _obj in mock_db.add.call_args_list:
            pass  # Evidence object is added
    mock_db.flush.side_effect = flush_side_effect

    builder.build_for_story(mock_db, story)
    # Evidence was added
    assert mock_db.add.called
    assert mock_db.flush.called


def test_build_for_story_updates_stable_evidence(builder, story, mock_db):
    """Rebuilding a story updates its current packet without changing evidence ID."""
    items = [_make_item(1, "Updated title", "Updated description")]
    items_query = MagicMock()
    items_query.join.return_value = items_query
    items_query.filter.return_value = items_query
    items_query.all.return_value = items
    evidence_query = MagicMock()
    evidence_query.filter_by.return_value = evidence_query
    evidence_query.order_by.return_value = evidence_query
    existing = MagicMock()
    existing.id = 42
    existing.packet = {"headline": "old"}
    evidence_query.first.return_value = existing
    mock_db.query.side_effect = [items_query, evidence_query]

    evidence_id = builder.build_for_story(mock_db, story)

    assert evidence_id == 42
    assert existing.packet["facts"][0] == "Updated title"
    mock_db.add.assert_not_called()
    mock_db.flush.assert_called_once()


def test_build_for_stories_stats(builder, mock_db):
    """build_for_stories returns packets_built count."""
    story2 = Story(id=2, headline="Test", cluster_keywords=[], source_count=1)

    # First query: Story lookup
    story_query = MagicMock()
    story_query.filter_by.return_value = story_query
    story_query.first.return_value = story2

    # Second query: items for story
    items_query = MagicMock()
    items_query.join.return_value = items_query
    items_query.filter.return_value = items_query
    items_query.all.return_value = [_make_item(1, "Title", "Desc")]

    evidence_query = MagicMock()
    evidence_query.filter_by.return_value = evidence_query
    evidence_query.order_by.return_value = evidence_query
    evidence_query.first.return_value = None

    mock_db.query.side_effect = [story_query, items_query, evidence_query]

    stats = builder.build_for_stories(mock_db, [2])
    assert stats["packets_built"] == 1


def test_build_for_stories_skips_missing(builder, mock_db):
    """Non-existent story_id → not counted."""
    story_query = MagicMock()
    story_query.filter_by.return_value = story_query
    story_query.first.return_value = None
    mock_db.query.return_value = story_query

    stats = builder.build_for_stories(mock_db, [999])
    assert stats["packets_built"] == 0
