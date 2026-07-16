"""Test source collectors — RSS parsing from fixture, GitHub URL parsing,
source validation."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from newsroom.sources.base import CollectionError, classify_retry
from newsroom.sources.github import GitHubCollector
from newsroom.sources.rss import RSSCollector

FIXTURES = Path(__file__).parent / "fixtures"


def _make_source(url="https://example.com/feed.xml", name="test", sid=1, stype="rss"):
    src = MagicMock()
    src.url = url
    src.name = name
    src.id = sid
    src.type = stype
    return src


# ── RSS validation ──────────────────────────────────────────────

def test_rss_validate_url_accepts_feed_paths():
    c = RSSCollector()
    assert c.validate_url("https://example.com/feed.xml") is True
    assert c.validate_url("https://example.com/rss") is True
    assert c.validate_url("https://blog.example.com/feed/") is True
    assert c.validate_url("http://example.com/atom.xml") is True
    assert c.validate_url("https://example.com/posts/default") is True


def test_rss_validate_url_rejects_non_feed():
    c = RSSCollector()
    assert c.validate_url("https://example.com/page.html") is False
    assert c.validate_url("ftp://example.com/feed.xml") is False
    assert c.validate_url("invalid") is False


# ── RSS parsing from fixture ────────────────────────────────────

@pytest.mark.asyncio
async def test_rss_parses_fixture_feed():
    """Parse the sample_rss.xml fixture — 3 items."""
    feed_xml = (FIXTURES / "sample_rss.xml").read_bytes()
    collector = RSSCollector()

    mock_response = MagicMock()
    mock_response.content = feed_xml
    mock_response.raise_for_status = MagicMock()

    with patch.object(collector.client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        items = await collector.collect(_make_source())

    assert len(items) == 3
    assert items[0]["title"] == "New Python Release 3.13"
    assert items[0]["link"] == "https://example.com/python-3.13"
    assert items[0]["type"] == "rss"
    assert "published" in items[0]

    await collector.close()


@pytest.mark.asyncio
async def test_rss_collector_handles_404():
    """HTTP 404 → recoverable CollectionError."""
    import httpx
    collector = RSSCollector()
    source = _make_source()

    with patch.object(collector.client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock(status_code=404)
        )
        with pytest.raises(CollectionError) as exc:
            await collector.collect(source)

    assert exc.value.recoverable is True
    await collector.close()


# ── GitHub URL parsing ──────────────────────────────────────────

def test_github_parse_repo_full_url():
    c = GitHubCollector()
    owner, repo = c._parse_repo("https://github.com/pytorch/pytorch")
    assert owner == "pytorch"
    assert repo == "pytorch"


def test_github_parse_repo_with_extra_path():
    """Extra path segments stripped — only owner/repo kept."""
    c = GitHubCollector()
    owner, repo = c._parse_repo("https://github.com/owner/repo/issues")
    assert owner == "owner"
    assert repo == "repo"


def test_github_parse_repo_with_trailing_slash():
    c = GitHubCollector()
    owner, repo = c._parse_repo("https://github.com/owner/repo/")
    assert owner == "owner"
    assert repo == "repo"


def test_github_parse_repo_shorthand():
    """Shorthand 'owner/repo' works."""
    c = GitHubCollector()
    owner, repo = c._parse_repo("owner/repo")
    assert owner == "owner"
    assert repo == "repo"


def test_github_parse_repo_invalid_raises():
    """Invalid format → non-recoverable CollectionError."""
    c = GitHubCollector()
    with pytest.raises(CollectionError) as exc:
        c._parse_repo("just-a-name")
    assert exc.value.recoverable is False


def test_github_parse_repo_single_segment_url():
    """https://github.com/owner → error (no repo)."""
    c = GitHubCollector()
    with pytest.raises(CollectionError):
        c._parse_repo("https://github.com/owner")


# ── GitHub validation ───────────────────────────────────────────

def test_github_validate_url():
    c = GitHubCollector()
    assert c.validate_url("https://github.com/owner/repo") is True
    assert c.validate_url("owner/repo") is True
    assert c.validate_url("https://example.com/feed.xml") is False


# ── GitHub collect from fixture ─────────────────────────────────

@pytest.mark.asyncio
async def test_github_parses_fixture_releases():
    """Parse the sample_github_releases.json fixture — 2 releases."""
    releases = json.loads((FIXTURES / "sample_github_releases.json").read_text())
    collector = GitHubCollector()
    source = _make_source(url="https://github.com/pytorch/pytorch", stype="github_releases")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = releases
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {}

    with patch.object(collector.client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        items = await collector.collect(source)

    assert len(items) == 2
    assert items[0]["type"] == "github_releases"
    assert items[0]["tag_name"] == "v2.5.0"
    assert items[0]["html_url"].startswith("https://github.com/")
    assert "body" in items[0]

    await collector.close()


# ── Error classification ────────────────────────────────────────

def test_classify_retry_recoverable():
    err = CollectionError("fail", "url", recoverable=True)
    assert classify_retry(err) == "retry"


def test_classify_retry_non_recoverable():
    err = CollectionError("fail", "url", recoverable=False)
    assert classify_retry(err) == "skip"


def test_classify_retry_generic_error():
    """Generic Exception → skip."""
    assert classify_retry(ValueError("oops")) == "skip"
