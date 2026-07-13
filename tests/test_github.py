"""Test GitHub collector."""

import json
from pathlib import Path

import pytest

from newsroom.sources.github import GitHubCollector


@pytest.fixture
def sample_releases():
    """Load sample GitHub releases fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_github_releases.json"
    return json.loads(fixture_path.read_text())


@pytest.mark.asyncio
async def test_github_collector_parses_releases(httpx_mock, sample_releases):
    """Test GitHub collector parses releases."""
    collector = GitHubCollector()

    httpx_mock.add_response(
        url="https://api.github.com/repos/pytorch/pytorch/releases",
        json=sample_releases,
        status_code=200,
    )

    items = await collector.collect("pytorch/pytorch")

    assert len(items) == 2
    assert items[0]["tag_name"] == "v2.5.0"
    assert items[0]["name"] == "v2.5.0"
    assert items[0]["html_url"] == "https://github.com/pytorch/pytorch/releases/tag/v2.5.0"
    assert items[0]["type"] == "github_releases"
    assert items[0]["author"] == "pytorch-bot"
    assert "published_at" in items[0]

    await collector.close()


@pytest.mark.asyncio
async def test_github_collector_validates_urls():
    """Test URL validation logic."""
    collector = GitHubCollector()

    assert collector.validate_url("pytorch/pytorch") is True
    assert collector.validate_url("python/cpython") is True
    assert collector.validate_url("pydantic/pydantic") is True
    assert collector.validate_url("owner/repo/subpath") is True

    assert collector.validate_url("invalid") is False
    assert collector.validate_url("") is False
    assert collector.validate_url("/") is False

    await collector.close()


@pytest.mark.asyncio
async def test_github_collector_handles_rate_limit(httpx_mock):
    """Test handling of rate limit errors."""
    from newsroom.sources.base import CollectionError

    collector = GitHubCollector()

    httpx_mock.add_response(
        url="https://api.github.com/repos/pytorch/pytorch/releases",
        status_code=403,
        headers={
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1720872000",
        },
    )

    with pytest.raises(CollectionError) as exc_info:
        await collector.collect("pytorch/pytorch")

    assert "rate limit" in str(exc_info.value).lower()
    assert exc_info.value.recoverable is True

    await collector.close()


@pytest.mark.asyncio
async def test_github_collector_handles_invalid_format(httpx_mock):
    """Test handling of invalid repo format."""
    from newsroom.sources.base import CollectionError

    collector = GitHubCollector()

    with pytest.raises(CollectionError) as exc_info:
        await collector.collect("invalid-format")

    assert "invalid" in str(exc_info.value).lower()
    assert exc_info.value.recoverable is False

    await collector.close()


@pytest.mark.asyncio
async def test_github_collector_handles_http_errors(httpx_mock):
    """Test handling of HTTP errors."""
    from newsroom.sources.base import CollectionError

    collector = GitHubCollector()

    httpx_mock.add_response(
        url="https://api.github.com/repos/nonexistent/repo/releases",
        status_code=404,
    )

    with pytest.raises(CollectionError) as exc_info:
        await collector.collect("nonexistent/repo")

    assert exc_info.value.recoverable is True

    await collector.close()
