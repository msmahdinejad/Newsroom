"""Test normalization pipeline."""

from datetime import datetime

import pytest

from newsroom.processing.normalize import Normalizer


@pytest.fixture
def normalizer():
    """Create normalizer instance."""
    return Normalizer()


def test_normalize_rss_item(normalizer):
    """Test normalizing RSS item."""
    raw_item = {
        "type": "rss",
        "title": "Python 3.13 Released",
        "description": "New Python version with improved performance",
        "link": "https://blog.python.org/2026/07/python-313.html?utm_source=feed",
        "published": "2026-07-13T10:00:00",
    }

    normalized = normalizer.normalize(raw_item)

    assert normalized["title"] == "Python 3.13 Released"
    assert normalized["description"] == "New Python version with improved performance"
    assert normalized["source_url"] == "https://blog.python.org/2026/07/python-313.html?utm_source=feed"
    assert normalized["normalized_url"] == "https://blog.python.org/2026/07/python-313.html"
    assert len(normalized["content_hash"]) == 64  # SHA-256 hex
    assert isinstance(normalized["published_at"], datetime)


def test_normalize_github_item(normalizer):
    """Test normalizing GitHub release item."""
    raw_item = {
        "type": "github_releases",
        "tag_name": "v2.5.0",
        "name": "PyTorch 2.5.0",
        "body": "## What's New\n\n- Feature A\n- Feature B",
        "html_url": "https://github.com/pytorch/pytorch/releases/tag/v2.5.0",
        "published_at": "2026-07-12T14:00:00Z",
    }

    normalized = normalizer.normalize(raw_item)

    assert normalized["title"] == "PyTorch 2.5.0"
    assert "Feature A" in normalized["description"]
    assert normalized["source_url"] == "https://github.com/pytorch/pytorch/releases/tag/v2.5.0"
    assert len(normalized["content_hash"]) == 64
    assert isinstance(normalized["published_at"], datetime)


def test_content_hash_deterministic(normalizer):
    """Test content hash is deterministic."""
    hash1 = normalizer._compute_hash("Title", "Description")
    hash2 = normalizer._compute_hash("Title", "Description")

    assert hash1 == hash2
    assert len(hash1) == 64


def test_content_hash_different_content(normalizer):
    """Test different content produces different hashes."""
    hash1 = normalizer._compute_hash("Title A", "Description A")
    hash2 = normalizer._compute_hash("Title B", "Description B")

    assert hash1 != hash2


def test_normalize_url_removes_tracking_params(normalizer):
    """Test URL normalization removes tracking parameters."""
    url = "https://example.com/article?utm_source=twitter&utm_campaign=promo&id=123"
    normalized = normalizer._normalize_url(url)

    assert normalized == "https://example.com/article?id=123"
    assert "utm_source" not in normalized
    assert "utm_campaign" not in normalized


def test_normalize_url_lowercase_domain(normalizer):
    """Test URL normalization lowercases domain."""
    url = "https://Example.Com/Article"
    normalized = normalizer._normalize_url(url)

    assert normalized == "https://example.com/Article"


def test_normalize_url_handles_empty(normalizer):
    """Test URL normalization handles empty string."""
    assert normalizer._normalize_url("") == ""


def test_normalize_url_handles_invalid(normalizer):
    """Test URL normalization handles invalid URLs."""
    # Should return original on parse failure
    url = "not-a-url"
    normalized = normalizer._normalize_url(url)

    assert normalized == url


def test_parse_timestamp_iso_format(normalizer):
    """Test parsing ISO 8601 timestamp."""
    timestamp = "2026-07-13T10:30:00"
    parsed = normalizer._parse_timestamp(timestamp)

    assert parsed is not None
    assert parsed.year == 2026
    assert parsed.month == 7
    assert parsed.day == 13


def test_parse_timestamp_with_z(normalizer):
    """Test parsing timestamp with Z suffix."""
    timestamp = "2026-07-13T10:30:00Z"
    parsed = normalizer._parse_timestamp(timestamp)

    assert parsed is not None


def test_parse_timestamp_handles_none(normalizer):
    """Test parsing None timestamp."""
    assert normalizer._parse_timestamp(None) is None


def test_parse_timestamp_handles_invalid(normalizer):
    """Test parsing invalid timestamp returns None."""
    assert normalizer._parse_timestamp("invalid") is None


def test_normalize_unknown_type_raises(normalizer):
    """Test normalizing unknown type raises ValueError."""
    raw_item = {"type": "unknown"}

    with pytest.raises(ValueError, match="Unknown item type"):
        normalizer.normalize(raw_item)


def test_github_fallback_to_tag_name(normalizer):
    """Test GitHub item uses tag_name when name is empty."""
    raw_item = {
        "type": "github_releases",
        "tag_name": "v1.0.0",
        "name": "",
        "body": "Release notes",
        "html_url": "https://github.com/owner/repo/releases/tag/v1.0.0",
        "published_at": "2026-07-13T10:00:00Z",
    }

    normalized = normalizer.normalize(raw_item)

    assert normalized["title"] == "v1.0.0"
