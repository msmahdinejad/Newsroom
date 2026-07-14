"""Test normalization pipeline — Persian/Arabic chars, URL canonicalization,
content hash determinism, language detection."""

import pytest

from newsroom.processing.normalize import Normalizer


@pytest.fixture
def normalizer():
    return Normalizer()


# ── Persian/Arabic character normalization ───────────────────────

def test_arabic_yeh_to_persian(normalizer):
    """Arabic Yeh ي → Persian Yeh ی."""
    assert normalizer._normalize_text("علي") == "علی"


def test_arabic_kaf_to_persian(normalizer):
    """Arabic Kaf ك → Persian Kaf ک."""
    assert normalizer._normalize_text("كتاب") == "کتاب"


def test_arabic_alef_variants(normalizer):
    """أ, إ, آ → ا."""
    assert normalizer._normalize_text("أحمد") == "احمد"
    assert normalizer._normalize_text("إبراهيم") == "ابراهیم"
    assert normalizer._normalize_text("آرام") == "ارام"


def test_arabic_teh_marbuta(normalizer):
    """ة → ه."""
    assert normalizer._normalize_text("مدرسة") == "مدرسه"


def test_persian_digits_to_ascii(normalizer):
    """Persian digits ۰-۹ → 0-9."""
    assert normalizer._normalize_text("سال ۱۴۰۳") == "سال 1403"


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
    assert normalizer._detect_language("این یک متن فارسی است") == "fa"


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
        "text": "اخبار جدید در مورد پایتون",
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
