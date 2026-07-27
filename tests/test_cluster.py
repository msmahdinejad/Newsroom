"""Test clustering — weighted Jaccard similarity, version compound keywords,
clustering positive/negative cases."""

from unittest.mock import MagicMock

import pytest

from newsroom.processing.cluster import Clusterer


@pytest.fixture
def clusterer():
    return Clusterer()


# ── Keyword extraction ──────────────────────────────────────────

def test_extract_keywords_basic(clusterer):
    kws = clusterer._extract_keywords("Python 3.13 released today")
    assert "python" in kws
    assert "released" in kws
    assert "today" in kws


def test_extract_keywords_filters_stopwords(clusterer):
    kws = clusterer._extract_keywords("the release of python is here")
    assert "python" in kws
    assert "release" in kws
    assert "the" not in kws
    assert "is" not in kws


def test_extract_keywords_version_compound(clusterer):
    """'python 3.13' → compound 'python-3' (regex splits on dot: '3','13')."""
    kws = clusterer._extract_keywords("python 3.13 released")
    assert "python-3" in kws


def test_extract_keywords_filters_short(clusterer):
    """Words ≤2 chars excluded."""
    kws = clusterer._extract_keywords("go to the sky now")
    assert "sky" in kws
    assert "go" not in kws
    assert "to" not in kws


def test_extract_keywords_persian(clusterer):
    """Persian chars in \u0600-\u06FF range are captured."""
    kws = clusterer._extract_keywords("پایتون نسخه جدید")
    assert "پایتون" in kws
    assert "نسخه" in kws
    assert "جدید" in kws


def test_extract_keywords_version_compound_persian_stopword(clusterer):
    """Stopword before digit doesn't create compound."""
    kws = clusterer._extract_keywords("is 3.13")
    # "is" is a stopword → no compound
    assert "is-3.13" not in kws


# ── Weighted Jaccard similarity ─────────────────────────────────

def test_similarity_identical_keywords(clusterer):
    a = {"python", "release", "version"}
    b = {"python", "release", "version"}
    assert clusterer._compute_similarity(a, b) == 1.0


def test_similarity_disjoint(clusterer):
    a = {"python", "release"}
    b = {"java", "update"}
    assert clusterer._compute_similarity(a, b) == 0.0


def test_similarity_empty(clusterer):
    assert clusterer._compute_similarity(set(), {"a"}) == 0.0
    assert clusterer._compute_similarity({"a"}, set()) == 0.0


def test_similarity_version_compound_double_weight(clusterer):
    """Version compounds get weight 2.0 — sharing one should boost similarity."""
    # With version compound shared (weight 2 each)
    a = {"python-3", "release"}
    b = {"python-3", "update"}
    # inter = 2.0 (python-3), union = 2+1+1 = 4.0 → 0.5
    assert clusterer._compute_similarity(a, b) == 0.5


def test_similarity_no_version_compound_lower(clusterer):
    """Same sets without version compounds — plain Jaccard."""
    a = {"python", "release"}
    b = {"python", "update"}
    # inter=1, union=3 → 1/3
    assert abs(clusterer._compute_similarity(a, b) - 1/3) < 0.001


def test_similarity_above_threshold(clusterer):
    """Two similar tech items should exceed default threshold 0.35."""
    a = clusterer._extract_keywords("Python 3.13 released with new features")
    b = clusterer._extract_keywords("Python 3.13 released with performance improvements")
    assert clusterer._compute_similarity(a, b) >= 0.35


def test_similarity_below_threshold(clusterer):
    """Unrelated items should be below threshold."""
    a = clusterer._extract_keywords("Python 3.13 released today")
    b = clusterer._extract_keywords("Weather forecast for tomorrow rain")
    assert clusterer._compute_similarity(a, b) < 0.35


def test_reddit_html_boilerplate_cannot_merge_unrelated_posts(clusterer):
    """Shared syndication markup is not evidence that two posts are one story."""
    backend = clusterer._extract_keywords(
        '<table><tr><td><a href="https://www.reddit.com/r/Backend/comments/a">'
        "AutoLock automatically locks a Windows PC"
        "</a><br/>submitted by user</td></tr></table>"
    )
    matlab = clusterer._extract_keywords(
        '<table><tr><td><a href="https://www.reddit.com/r/matlab/comments/b">'
        "Simple C++ framework for math and data"
        "</a><br/>submitted by user</td></tr></table>"
    )

    assert clusterer._compute_similarity(backend, matlab) < 0.35


# ── Clustering with mock DB ─────────────────────────────────────

def _make_norm_item(item_id, title, description=""):
    """Create a mock NormalizedItem."""
    item = MagicMock()
    item.id = item_id
    item.title = title
    item.description = description
    item.is_duplicate = False
    item.raw_item = MagicMock()
    item.raw_item.source_id = 1
    return item


def test_cluster_groups_similar_items(clusterer, mock_db):
    """Two similar items → one story with 2 items."""
    item1 = _make_norm_item(1, "Python 3.13 released with new features")
    item2 = _make_norm_item(2, "Python 3.13 released with performance improvements")
    items = [item1, item2]

    # query returns our items (no duplicates), no existing story links
    q = mock_db.query.return_value
    q.filter.return_value = q
    q.all.return_value = items
    # StoryItem query returns empty (no existing links)
    mock_db.query.return_value.filter.return_value.all.return_value = items

    # We need two separate query chains: one for NormalizedItem, one for StoryItem
    # Use side_effect to return different query objects
    norm_query = MagicMock()
    norm_query.filter.return_value = norm_query
    norm_query.all.return_value = items

    story_query = MagicMock()
    story_query.filter.return_value = story_query
    story_query.all.return_value = []  # no existing links

    mock_db.query.side_effect = [norm_query, story_query]

    stats = clusterer.cluster_items(mock_db, [1, 2])
    assert stats["stories_created"] >= 1
    assert stats["items_clustered"] >= 2


def test_cluster_separates_dissimilar_items(clusterer, mock_db):
    """Dissimilar items → separate stories."""
    item1 = _make_norm_item(1, "Python 3.13 released today")
    item2 = _make_norm_item(2, "Weather forecast rain tomorrow")
    items = [item1, item2]

    norm_query = MagicMock()
    norm_query.filter.return_value = norm_query
    norm_query.all.return_value = items

    story_query = MagicMock()
    story_query.filter.return_value = story_query
    story_query.all.return_value = []

    mock_db.query.side_effect = [norm_query, story_query]

    stats = clusterer.cluster_items(mock_db, [1, 2])
    assert stats["stories_created"] == 2


def test_cluster_skips_duplicates(clusterer, mock_db):
    """Duplicate items (is_duplicate=True) are excluded."""
    norm_query = MagicMock()
    norm_query.filter.return_value = norm_query
    norm_query.all.return_value = []  # no non-duplicate items

    mock_db.query.return_value = norm_query

    stats = clusterer.cluster_items(mock_db, [1, 2])
    assert stats["stories_created"] == 0
    assert stats["items_clustered"] == 0


# ── Story creation ──────────────────────────────────────────────

def test_create_story_single_item(clusterer, mock_db):
    """Single item → story with source_count=1, trust=unconfirmed."""
    item = _make_norm_item(1, "Python 3.13 released")
    story = clusterer._create_story(mock_db, [item])
    assert story.source_count == 1
    assert story.trust_status == "unconfirmed"
    assert story.importance_score > 0
    assert len(story.headline) > 0


def test_create_story_multi_source(clusterer, mock_db):
    """Items from 3 sources → trust=confirmed."""
    items = []
    for i in range(3):
        item = _make_norm_item(i + 1, f"Python 3.13 release {i}")
        item.raw_item.source_id = i + 1  # distinct sources
        items.append(item)
    story = clusterer._create_story(mock_db, items)
    assert story.source_count == 3
    assert story.trust_status == "confirmed"
    assert abs(story.confidence - 0.9) < 0.001  # min(3*0.3, 1.0), float-safe
