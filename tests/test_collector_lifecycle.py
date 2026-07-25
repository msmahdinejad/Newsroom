"""Collector lifecycle regression tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from newsroom.pipeline.collect import _bounded_fair_sources, collect_sources
from newsroom.sources.base import CollectionError


def test_bounded_batch_round_robins_across_source_types() -> None:
    now = datetime.now(UTC)
    sources = [
        SimpleNamespace(id=1, type="reddit_subreddit", last_attempt_at=now - timedelta(days=4)),
        SimpleNamespace(id=2, type="reddit_subreddit", last_attempt_at=now - timedelta(days=3)),
        SimpleNamespace(id=3, type="reddit_subreddit", last_attempt_at=now - timedelta(days=2)),
        SimpleNamespace(id=4, type="rss", last_attempt_at=now - timedelta(days=1)),
        SimpleNamespace(id=5, type="web_page", last_attempt_at=now),
    ]

    selected = _bounded_fair_sources(sources, 4)

    assert [source.id for source in selected] == [1, 4, 5, 2]
    assert {source.type for source in selected[:3]} == {
        "reddit_subreddit",
        "rss",
        "web_page",
    }


@pytest.mark.asyncio
async def test_collect_sources_closes_every_collector() -> None:
    """Repeated production cycles must not leak HTTP clients."""
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    collectors = [MagicMock(close=AsyncMock()) for _ in range(6)]

    with (
        patch("newsroom.pipeline.collect.RSSCollector", return_value=collectors[0]),
        patch("newsroom.pipeline.collect.GitHubCollector", return_value=collectors[1]),
        patch("newsroom.pipeline.collect.TelegramMTProtoCollector", return_value=collectors[2]),
        patch("newsroom.pipeline.collect.NativeHtmlReader", return_value=collectors[3]),
        patch(
            "newsroom.pipeline.collect.NativeRedditSubredditCollector",
            return_value=collectors[4],
        ),
        patch("newsroom.pipeline.collect.NativeYouTubeRssCollector", return_value=collectors[5]),
    ):
        result = await collect_sources(session)

    assert result["sources"] == 0
    for collector in collectors:
        collector.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_collect_sources_isolates_and_safely_classifies_one_failure() -> None:
    """A failed source is degraded safely and does not stop the next source."""
    bad = SimpleNamespace(
        id=1,
        name="bad",
        type="rss",
        url="https://example.com/bad",
        enabled=True,
        consecutive_failures=0,
        health_status="healthy",
        no_cursor_reason=None,
    )
    good = SimpleNamespace(
        id=2,
        name="good",
        type="rss",
        url="https://example.com/good",
        enabled=True,
        consecutive_failures=0,
        health_status="unknown",
        no_cursor_reason=None,
    )
    query = MagicMock()
    query.filter.return_value = query
    query.filter_by.return_value = query
    query.all.return_value = [bad, good]
    query.first.return_value = None
    session = MagicMock()
    session.query.return_value = query

    rss = MagicMock(close=AsyncMock())

    async def collect(source):
        if source is bad:
            raise CollectionError("HTTP 429 token=protected-value", source.url)
        return []

    rss.collect = AsyncMock(side_effect=collect)
    other_collectors = [MagicMock(close=AsyncMock()) for _ in range(5)]
    with (
        patch("newsroom.pipeline.collect.RSSCollector", return_value=rss),
        patch("newsroom.pipeline.collect.GitHubCollector", return_value=other_collectors[0]),
        patch(
            "newsroom.pipeline.collect.TelegramMTProtoCollector",
            return_value=other_collectors[1],
        ),
        patch("newsroom.pipeline.collect.NativeHtmlReader", return_value=other_collectors[2]),
        patch(
            "newsroom.pipeline.collect.NativeRedditSubredditCollector",
            return_value=other_collectors[3],
        ),
        patch(
            "newsroom.pipeline.collect.NativeYouTubeRssCollector",
            return_value=other_collectors[4],
        ),
    ):
        result = await collect_sources(session)

    assert result["sources"] == 2
    assert result["failed"] == ["bad"]
    assert rss.collect.await_count == 2
    assert bad.health_status == "degraded"
    assert bad.failure_category == "rate_limit"
    assert "protected-value" not in bad.last_error
    assert good.health_status == "healthy"


@pytest.mark.asyncio
async def test_bounded_batch_selects_least_recently_attempted_source() -> None:
    now = datetime.now(UTC)

    def source(source_id: int, name: str, attempted_at: datetime):
        return SimpleNamespace(
            id=source_id,
            name=name,
            type="unsupported",
            url="https://example.com/",
            enabled=True,
            last_attempt_at=attempted_at,
            last_success_at=None,
            last_error_at=None,
            failure_category=None,
            validation_status=None,
            no_cursor_reason=None,
        )

    newer = source(2, "newer", now)
    older = source(1, "older", now - timedelta(days=1))
    query = MagicMock()
    query.filter.return_value = query
    query.all.return_value = [newer, older]
    session = MagicMock()
    session.query.return_value = query
    collectors = [MagicMock(close=AsyncMock()) for _ in range(6)]
    with (
        patch("newsroom.pipeline.collect.RSSCollector", return_value=collectors[0]),
        patch("newsroom.pipeline.collect.GitHubCollector", return_value=collectors[1]),
        patch("newsroom.pipeline.collect.TelegramMTProtoCollector", return_value=collectors[2]),
        patch("newsroom.pipeline.collect.NativeHtmlReader", return_value=collectors[3]),
        patch(
            "newsroom.pipeline.collect.NativeRedditSubredditCollector",
            return_value=collectors[4],
        ),
        patch("newsroom.pipeline.collect.NativeYouTubeRssCollector", return_value=collectors[5]),
    ):
        result = await collect_sources(session, max_sources=1)

    assert result["sources"] == 1
    assert result["detail"][0]["source"] == "older"
