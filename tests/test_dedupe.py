"""Test deduplication — exact hash, URL hash, near-duplicate token similarity."""

import hashlib

import pytest

from newsroom.processing.dedupe import Deduplicator


@pytest.fixture
def dedupe():
    return Deduplicator()


# ── Tokenization ────────────────────────────────────────────────

def test_tokenize_simple(dedupe):
    tokens = dedupe._tokenize("Python 3.13 released today")
    assert "python" in tokens
    assert "released" in tokens
    assert "today" in tokens


def test_tokenize_filters_short_words(dedupe):
    """Words ≤2 chars are excluded; 3-char words pass."""
    tokens = dedupe._tokenize("a go to the sky")
    assert "sky" in tokens
    assert "the" in tokens  # len("the")==3 > 2 → kept
    assert "a" not in tokens
    assert "go" not in tokens  # len("go")==2 ≤ 2 → filtered
    assert "to" not in tokens


def test_tokenize_lowercase(dedupe):
    tokens = dedupe._tokenize("PYTHON ReleaseD")
    assert "python" in tokens
    assert "released" in tokens


def test_tokenize_empty(dedupe):
    assert dedupe._tokenize("") == set()


# ── Token similarity (Jaccard) ──────────────────────────────────

def test_similarity_identical(dedupe):
    a = {"python", "release", "version"}
    b = {"python", "release", "version"}
    assert dedupe._token_similarity(a, b) == 1.0


def test_similarity_disjoint(dedupe):
    a = {"python", "release"}
    b = {"java", "update"}
    assert dedupe._token_similarity(a, b) == 0.0


def test_similarity_partial(dedupe):
    a = {"python", "release", "version"}
    b = {"python", "release", "update"}
    # intersection=2, union=4 → 0.5
    assert dedupe._token_similarity(a, b) == 0.5


def test_similarity_empty_set(dedupe):
    assert dedupe._token_similarity(set(), {"a"}) == 0.0
    assert dedupe._token_similarity({"a"}, set()) == 0.0


def test_similarity_above_threshold(dedupe):
    """Near-duplicate titles should score ≥ 0.7."""
    t1 = dedupe._tokenize("Python 3.13 released with new features today")
    t2 = dedupe._tokenize("Python 3.13 released with new features update")
    # tokens (len>2): python, released, with, new, features, today / update
    # intersection: 5, union: 7 → 0.714
    assert dedupe._token_similarity(t1, t2) >= 0.7


# ── Empty hash ──────────────────────────────────────────────────

def test_empty_hash(dedupe):
    expected = hashlib.sha256(b"").hexdigest()
    assert dedupe._empty_hash() == expected


# ── _mark_if_duplicate with mock DB ─────────────────────────────

def _make_item(item_id, content_hash, url_hash="", title="Test"):
    """Create a mock NormalizedItem-like object."""
    from unittest.mock import MagicMock
    item = MagicMock()
    item.id = item_id
    item.content_hash = content_hash
    item.url_hash = url_hash
    item.title = title
    item.is_duplicate = False
    item.duplicate_of_id = None
    return item


def test_exact_hash_duplicate_detected(dedupe, mock_db):
    """Item with same content_hash as earlier item → marked 'hash'."""
    original = _make_item(1, "abc123", "url1", "Original")
    new_item = _make_item(2, "abc123", "url2", "Duplicate")

    # First query (hash check) finds the original
    q = mock_db.query.return_value
    q.filter.return_value = q
    q.first.return_value = original

    method = dedupe._mark_if_duplicate(mock_db, new_item)
    assert method == "hash"
    assert new_item.is_duplicate is True
    assert new_item.duplicate_of_id == 1


def test_url_hash_duplicate_detected(dedupe, mock_db):
    """Same url_hash, different content_hash → marked 'url'."""
    original = _make_item(1, "hash_a", "same_url_hash", "Title A")
    new_item = _make_item(2, "hash_b", "same_url_hash", "Title B")

    q = mock_db.query.return_value
    q.filter.return_value = q
    # First query (hash) → None, second query (url) → original
    q.first.side_effect = [None, original]

    method = dedupe._mark_if_duplicate(mock_db, new_item)
    assert method == "url"
    assert new_item.is_duplicate is True


def test_no_duplicate_found(dedupe, mock_db):
    """No hash, url, or near-duplicate → None."""
    new_item = _make_item(2, "unique_hash", "unique_url", "Unique Title")

    q = mock_db.query.return_value
    q.filter.return_value = q
    q.first.return_value = None  # no hash match, no url match
    q.all.return_value = []      # no near-dup candidates

    method = dedupe._mark_if_duplicate(mock_db, new_item)
    assert method is None
    assert new_item.is_duplicate is False
