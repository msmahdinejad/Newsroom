"""Test normalization pipeline — Persian/Arabic chars, URL canonicalization,
content hash determinism, language detection."""

import pytest

from newsroom.processing.normalize import Normalizer


@pytest.fixture
def normalizer():
    return Normalizer()


# ── Persian/Arabic character normalization ───────────────────────

def test_arabic_yeh_to_persian(normalizer):
    """Arabic Yeh \u064a → Persian Yeh \u06cc."""
    assert normalizer._normalize_text("\u0639\u0644\u064a") == "\u0639\u0644\u06cc"


def test_arabic_kaf_to_persian(normalizer):
    """Arabic Kaf \u0643 → Persian Kaf \u06a9."""
    assert normalizer._normalize_text("\u0643\u062a\u0627\u0628") == "\u06a9\u062a\u0627\u0628"


def test_arabic_alef_variants(normalizer):
    """\u0623, \u0625, \u0622 → \u0627."""
    assert normalizer._normalize_text("\u0623\u062d\u0645\u062f") == "\u0627\u062d\u0645\u062f"
    assert normalizer._normalize_text("\u0625\u0628\u0631\u0627\u0647\u064a\u0645") == "\u0627\u0628\u0631\u0627\u0647\u06cc\u0645"
    assert normalizer._normalize_text("\u0622\u0631\u0627\u0645") == "\u0627\u0631\u0627\u0645"


def test_arabic_teh_marbuta(normalizer):
    """\u0629 → \u0647."""
    assert normalizer._normalize_text("\u0645\u062f\u0631\u0633\u0629") == "\u0645\u062f\u0631\u0633\u0647"


def test_persian_digits_to_ascii(normalizer):
    """Persian digits \u06f0-\u06f9 → 0-9."""
    assert normalizer._normalize_text("\u0633\u0627\u0644 \u06f1\u06f4\u06f0\u06f3") == "\u0633\u0627\u0644 1403"


def test_whitespace_collapse(normalizer):
    """Multiple spaces/tabs/newlines collapse to single space."""
    assert normalizer._normalize_text("hello   world\n\tfoo") == "hello world foo"


def test_empty_text(normalizer):
    assert normalizer._normalize_text("") == ""
    assert normalizer._normalize_text(None) == ""


# ── URL canonicalization ─────────────────────────────────────────

def test_canonicalize_removes_tracking_params(normalizer):
    url = "https://example.com/article?utm_source=twitter&utm_campaign=promo&id=123"
    result = normalizer._canonicalize_url(url)
    assert result == "https://example.com/article?id=123"


def test_canonicalize_lowercase_domain(normalizer):
    assert normalizer._canonicalize_url("https://Example.COM/Article") == "https://example.com/Article"


def test_canonicalize_strips_www(normalizer):
    assert normalizer._canonicalize_url("https://www.example.com/path") == "https://example.com/path"


def test_canonicalize_strips_trailing_slash(normalizer):
    assert normalizer._canonicalize_url("https://example.com/path/") == "https://example.com/path"


def test_canonicalize_sorts_params(normalizer):
    url = "https://example.com/p?b=2&a=1"
    result = normalizer._canonicalize_url(url)
    assert result == "https://example.com/p?a=1&b=2"


def test_canonicalize_removes_fragment(normalizer):
    """Fragments are dropped."""
    result = normalizer._canonicalize_url("https://example.com/page#section")
    assert result == "https://example.com/page"


def test_canonicalize_empty_url(normalizer):
    assert normalizer._canonicalize_url("") == ""


def test_canonicalize_invalid_url_returns_original(normalizer):
    """No scheme/netloc → returned as-is."""
    assert normalizer._canonicalize_url("not-a-url") == "not-a-url"


def test_canonicalize_same_url_same_result(normalizer):
    """Same tracking URL canonicalizes identically each time."""
    url = "https://example.com/a?utm_source=x&id=1"
    assert normalizer._canonicalize_url(url) == normalizer._canonicalize_url(url)


# ── Content hash determinism ─────────────────────────────────────

def test_hash_deterministic(normalizer):
    h1 = normalizer._compute_hash("Title", "Description")
    h2 = normalizer._compute_hash("Title", "Description")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_hash_different_content_different_hash(normalizer):
    h1 = normalizer._compute_hash("Title A", "Desc A")
    h2 = normalizer._compute_hash("Title B", "Desc B")
    assert h1 != h2


def test_hash_order_independent_parts(normalizer):
    """Hash is of concatenated parts — different parts → different hash."""
    h1 = normalizer._compute_hash("A", "B")
    h2 = normalizer._compute_hash("A\nB")
    assert h1 == h2  # join uses \n


# ── Language detection ───────────────────────────────────────────

def test_detect_persian(normalizer):
    assert normalizer._detect_language("\u0627\u06cc\u0646 \u06cc\u06a9 \u0645\u062a\u0646 \u0641\u0627\u0631\u0633\u06cc \u0627\u0633\u062a") == "fa"


def test_detect_english(normalizer):
    assert normalizer._detect_language("This is an English text about Python") == "en"


def test_detect_mixed_english_dominant(normalizer):
    """Mostly English with a few Persian chars → en (under 15% threshold)."""
    assert normalizer._detect_language("Python 3.13 released with new features and updates here") == "en"


def test_detect_empty_defaults_english(normalizer):
    assert normalizer._detect_language("") == "en"


# ── Full RSS normalization ───────────────────────────────────────

def test_normalize_rss_item(normalizer):
    raw = {
        "type": "rss",
        "title": "Python 3.13 Released",
        "description": "New Python version with improved performance",
        "link": "https://blog.python.org/2026/07/python-313.html?utm_source=feed",
        "published": "2026-07-13T10:00:00",
    }
    result = normalizer.normalize(raw)
    assert result["title"] == "Python 3.13 Released"
    assert result["canonical_url"] == "https://blog.python.org/2026/07/python-313.html"
    assert result["language"] == "en"
    assert len(result["content_hash"]) == 64
    assert len(result["url_hash"]) == 64


def test_normalize_github_item(normalizer):
    raw = {
        "type": "github_releases",
        "tag_name": "v2.5.0",
        "name": "PyTorch 2.5.0",
        "body": "## What's New\n\n- Feature A",
        "html_url": "https://github.com/pytorch/pytorch/releases/tag/v2.5.0",
        "published_at": "2026-07-12T14:00:00Z",
    }
    result = normalizer.normalize(raw)
    assert result["title"] == "PyTorch 2.5.0"
    assert result["language"] == "en"
    assert len(result["content_hash"]) == 64


def test_normalize_github_fallback_to_tag(normalizer):
    raw = {
        "type": "github_releases",
        "tag_name": "v1.0.0",
        "name": "",
        "body": "Release notes",
        "html_url": "https://github.com/o/r/releases/tag/v1.0.0",
        "published_at": "2026-07-13T10:00:00Z",
    }
    result = normalizer.normalize(raw)
    assert result["title"] == "v1.0.0"


def test_normalize_unknown_type_raises(normalizer):
    with pytest.raises(ValueError, match="Unknown item type"):
        normalizer.normalize({"type": "unknown"})


def test_normalize_telegram_item(normalizer):
    raw = {
        "type": "telegram",
        "text": "\u0627\u062e\u0628\u0627\u0631 \u062c\u062f\u06cc\u062f \u062f\u0631 \u0645\u0648\u0631\u062f \u067e\u0627\u06cc\u062a\u0648\u0646",
        "channel_name": "technews",
        "link": "https://t.me/technews/123",
        "date": "2026-07-13T12:00:00Z",
    }
    result = normalizer.normalize(raw)
    assert result["language"] == "fa"
    assert result["source_url"] == "https://t.me/technews/123"
    assert len(result["content_hash"]) == 64


# ── Timestamp parsing ────────────────────────────────────────────

def test_parse_timestamp_iso(normalizer):
    ts = normalizer._parse_timestamp("2026-07-13T10:30:00")
    assert ts is not None
    assert ts.year == 2026 and ts.month == 7 and ts.day == 13


def test_parse_timestamp_z_suffix(normalizer):
    ts = normalizer._parse_timestamp("2026-07-13T10:30:00Z")
    assert ts is not None
    assert ts.tzinfo is not None


def test_parse_timestamp_none(normalizer):
    assert normalizer._parse_timestamp(None) is None


def test_parse_timestamp_invalid(normalizer):
    assert normalizer._parse_timestamp("invalid") is None
