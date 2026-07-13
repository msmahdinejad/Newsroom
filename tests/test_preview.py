"""Test Persian preview generator."""

import pytest

from newsroom.digest.preview import PreviewGenerator
from newsroom.storage.models import Digest, Source, Story


@pytest.fixture
def sample_source(db_session):
    """Create test source."""
    source = Source(name="Test", type="rss", url="https://example.com")
    db_session.add(source)
    db_session.commit()
    return source


@pytest.fixture
def generator():
    """Create preview generator."""
    return PreviewGenerator()


def test_generate_preview_with_stories(db_session, sample_source, generator):
    """Test generating preview from stories."""
    # Create story
    story = Story(
        headline="Python 3.13 Released",
        source_urls="['https://python.org/news', 'https://example.com/python']",
        item_ids="[1, 2]",
        priority="high",
    )
    db_session.add(story)
    db_session.commit()

    preview = generator.generate_preview([story.id])

    assert "گزارش خبری" in preview
    assert "مهم‌ترین خبرها" in preview
    assert "Python 3.13 Released" in preview
    assert "https://python.org/news" in preview
    assert "منابع: 2 منبع" in preview


def test_generate_preview_with_priority_sections(db_session, generator):
    """Test preview groups stories by priority."""
    high = Story(
        headline="Major Release",
        source_urls="['https://example.com/1']",
        item_ids="[1]",
        priority="high",
    )
    medium = Story(
        headline="Update Available",
        source_urls="['https://example.com/2']",
        item_ids="[2]",
        priority="medium",
    )
    low = Story(
        headline="Minor Fix",
        source_urls="['https://example.com/3']",
        item_ids="[3]",
        priority="low",
    )
    db_session.add_all([high, medium, low])
    db_session.commit()

    preview = generator.generate_preview([high.id, medium.id, low.id])

    assert "مهم‌ترین خبرها" in preview
    assert "اخبار مهم" in preview
    assert "ریزخبرها" in preview

    # Verify order
    idx_high = preview.index("مهم‌ترین خبرها")
    idx_medium = preview.index("اخبار مهم")
    idx_low = preview.index("ریزخبرها")
    assert idx_high < idx_medium < idx_low


def test_generate_preview_detailed_vs_compact(db_session, generator):
    """Test detailed format for high priority, compact for low."""
    high = Story(
        headline="High Priority",
        source_urls="['https://a.com', 'https://b.com']",
        item_ids="[1]",
        priority="high",
    )
    low = Story(
        headline="Low Priority",
        source_urls="['https://c.com', 'https://d.com']",
        item_ids="[2]",
        priority="low",
    )
    db_session.add_all([high, low])
    db_session.commit()

    preview = generator.generate_preview([high.id, low.id])

    # High priority shows multiple sources
    assert "https://a.com" in preview
    assert "https://b.com" in preview

    # Low priority shows only first source (compact)
    assert "https://c.com" in preview
    # Second source might appear if format includes it


def test_generate_preview_limits_sources(db_session, generator):
    """Test preview limits sources to 5 per story."""
    urls = [f"https://example.com/{i}" for i in range(10)]
    story = Story(
        headline="Many Sources",
        source_urls=str(urls),
        item_ids="[1]",
        priority="high",
    )
    db_session.add(story)
    db_session.commit()

    preview = generator.generate_preview([story.id])

    # Should show first 5 + "و X منبع دیگر"
    assert "https://example.com/0" in preview
    assert "https://example.com/4" in preview
    assert "منبع دیگر" in preview


def test_generate_empty_digest(generator):
    """Test generating digest with no stories."""
    preview = generator.generate_preview([])

    assert "گزارش خبری" in preview
    assert "خبر جدیدی" in preview
    assert "یافت نشد" in preview


def test_create_digest_persists(db_session, generator):
    """Test creating digest saves to database."""
    story = Story(
        headline="Test Story",
        source_urls="['https://example.com']",
        item_ids="[1]",
        priority="medium",
    )
    db_session.add(story)
    db_session.commit()

    digest_id = generator.create_digest([story.id])

    digest = db_session.query(Digest).filter(Digest.id == digest_id).first()
    assert digest is not None
    assert "Test Story" in digest.content_fa
    assert digest.delivered is False
    assert str(story.id) in digest.story_ids


def test_preview_includes_header_and_footer(db_session, generator):
    """Test preview has proper structure."""
    story = Story(
        headline="Story",
        source_urls="['https://example.com']",
        item_ids="[1]",
        priority="medium",
    )
    db_session.add(story)
    db_session.commit()

    preview = generator.generate_preview([story.id])

    # Header
    assert "گزارش خبری" in preview
    assert "تاریخ:" in preview

    # Footer
    assert "شامل" in preview
    assert "خبر" in preview
    assert "سیستم خبرخوان" in preview


def test_format_story_compact_mode(generator):
    """Test compact story formatting."""
    story = Story(
        id=1,
        headline="Compact Test",
        source_urls="['https://example.com/a', 'https://example.com/b']",
        item_ids="[1]",
        priority="low",
    )

    formatted = generator._format_story(story, detailed=False)

    assert "Compact Test" in formatted
    assert "•" in formatted
    assert "https://example.com/a" in formatted
    # Second URL should not appear in compact mode


def test_format_story_detailed_mode(generator):
    """Test detailed story formatting."""
    story = Story(
        id=1,
        headline="Detailed Test",
        source_urls="['https://a.com', 'https://b.com', 'https://c.com']",
        item_ids="[1, 2, 3]",
        priority="high",
    )

    formatted = generator._format_story(story, detailed=True)

    assert "Detailed Test" in formatted
    assert "📰" in formatted
    assert "منابع: 3 منبع" in formatted
    assert "https://a.com" in formatted
    assert "https://b.com" in formatted
    assert "https://c.com" in formatted
