"""Test source collector base protocol."""

import pytest

from newsroom.sources.base import CollectionError, SourceCollector


class MockCollector(SourceCollector):
    """Mock collector for testing."""

    async def collect(self, source_url: str) -> list[dict]:
        if source_url == "fail":
            raise CollectionError("Simulated failure", source_url)
        return [{"title": "Test", "url": source_url}]

    def validate_url(self, source_url: str) -> bool:
        return source_url.startswith("https://")


def test_collection_error_attributes():
    """Test CollectionError captures source context."""
    err = CollectionError("Network timeout", "https://example.com/feed", recoverable=True)

    assert str(err) == "Network timeout"
    assert err.source_url == "https://example.com/feed"
    assert err.recoverable is True


def test_collection_error_unrecoverable():
    """Test marking errors as unrecoverable."""
    err = CollectionError("Invalid format", "https://bad.xml", recoverable=False)

    assert err.recoverable is False


@pytest.mark.asyncio
async def test_mock_collector_success():
    """Test successful collection."""
    collector = MockCollector()
    result = await collector.collect("https://example.com")

    assert len(result) == 1
    assert result[0]["title"] == "Test"


@pytest.mark.asyncio
async def test_mock_collector_failure():
    """Test collection failure raises expected error."""
    collector = MockCollector()

    with pytest.raises(CollectionError) as exc_info:
        await collector.collect("fail")

    assert exc_info.value.source_url == "fail"


def test_url_validation():
    """Test URL validation."""
    collector = MockCollector()

    assert collector.validate_url("https://example.com/feed") is True
    assert collector.validate_url("http://example.com/feed") is False
    assert collector.validate_url("invalid") is False
