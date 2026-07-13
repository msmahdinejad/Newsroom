"""Test RSS collector."""

from pathlib import Path

import pytest

from newsroom.sources.rss import RSSCollector


@pytest.fixture
def sample_rss():
    """Load sample RSS fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_rss.xml"
    return fixture_path.read_text()


@pytest.mark.asyncio
async def test_rss_collector_parses_feed(httpx_mock, sample_rss):
    """Test RSS collector parses valid feed."""
    collector = RSSCollector()

    httpx_mock.add_response(
        url="https://example.com/feed.xml",
        content=sample_rss.encode("utf-8"),
        status_code=200,
    )

    items = await collector.collect("https://example.com/feed.xml")

    assert len(items) == 3
    assert items[0]["title"] == "New Python Release 3.13"
    assert items[0]["link"] == "https://example.com/python-3.13"
    assert items[0]["type"] == "rss"
    assert "published" in items[0]

    await collector.close()


@pytest.mark.asyncio
async def test_rss_collector_validates_urls():
    """Test URL validation logic."""
    collector = RSSCollector()

    assert collector.validate_url("https://example.com/feed.xml") is True
    assert collector.validate_url("https://example.com/rss") is True
    assert collector.validate_url("https://blog.example.com/feed/") is True
    assert collector.validate_url("http://example.com/atom.xml") is True

    assert collector.validate_url("https://example.com/page.html") is False
    assert collector.validate_url("ftp://example.com/feed.xml") is False
    assert collector.validate_url("invalid") is False

    await collector.close()


@pytest.mark.asyncio
async def test_rss_collector_handles_http_errors(httpx_mock):
    """Test handling of HTTP errors."""
    from newsroom.sources.base import CollectionError

    collector = RSSCollector()

    httpx_mock.add_response(
        url="https://example.com/feed.xml",
        status_code=404,
    )

    with pytest.raises(CollectionError) as exc_info:
        await collector.collect("https://example.com/feed.xml")

    assert exc_info.value.recoverable is True

    await collector.close()


@pytest.mark.asyncio
async def test_rss_collector_enforces_size_limit(httpx_mock):
    """Test size limit enforcement."""
    from newsroom.sources.base import CollectionError

    collector = RSSCollector()

    # Create content larger than 1MB limit
    large_content = b"x" * (2 * 1024 * 1024)

    httpx_mock.add_response(
        url="https://example.com/huge.xml",
        content=large_content,
        status_code=200,
    )

    with pytest.raises(CollectionError) as exc_info:
        await collector.collect("https://example.com/huge.xml")

    assert "too large" in str(exc_info.value).lower()
    assert exc_info.value.recoverable is False

    await collector.close()
