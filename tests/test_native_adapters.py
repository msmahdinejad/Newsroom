"""Deterministic tests for the Gate 6 native read-only adapters.

DB-free, network-free: httpx is mocked. Covers the native HTML reader,
Reddit subreddit JSON collector, and YouTube RSS collector (parsing + error
classification + SSRF rejection).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from newsroom.sources.base import CollectionError
from newsroom.sources.html_reader import NativeHtmlReader
from newsroom.sources.reddit import NativeRedditSubredditCollector
from newsroom.sources.youtube_rss import NativeYouTubeRssCollector


def _src(url, name="t", sid=1, stype="web_page", cfg=None):
    s = MagicMock()
    s.url = url
    s.name = name
    s.id = sid
    s.type = stype
    s.config = cfg or {}
    return s


# ── Native HTML reader ───────────────────────────────────────────


HTML_PAGE = """
<html><head>
<title>AI News — Latest</title>
<meta name="description" content="AI news and research"/>
<link rel="alternate" type="application/rss+xml" href="/feed.xml"/>
</head><body>
<article><a href="/posts/openai-launch">OpenAI launches new model</a></article>
<a href="/posts/anthropic">Anthropic release</a>
<a href="https://example.com/posts/dup">Dup</a>
<a href="https://example.com/posts/dup">Dup again</a>
<a href="mailto:x@y.com">mail</a>
</body></html>
"""


@pytest.mark.asyncio
async def test_html_reader_extracts_links_and_feed():
    c = NativeHtmlReader()
    resp = MagicMock()
    resp.content = HTML_PAGE.encode()
    resp.text = HTML_PAGE
    resp.raise_for_status = MagicMock()
    with patch.object(c.client, "get", new_callable=AsyncMock) as mg:
        mg.return_value = resp
        items = await c.collect(_src("https://example.com/"))
    titles = [i["title"] for i in items]
    assert "OpenAI launches new model" in titles
    assert "Anthropic release" in titles
    # mailto links excluded
    assert not any("mail" in i["link"] for i in items)
    # duplicate link deduped
    assert sum(1 for i in items if i["link"].endswith("/dup")) == 1
    # page-level item carries discovered feed
    page = [i for i in items if i.get("collected_via", "").endswith("_page")][0]
    assert "https://example.com/feed.xml" in page["discovered_feed_urls"]
    await c.close()


@pytest.mark.asyncio
async def test_html_reader_emits_one_identity_for_source_page():
    c = NativeHtmlReader()
    page = '<html><title>Home</title><a href="/">Home link</a></html>'
    resp = MagicMock()
    resp.status_code = 200
    resp.content = page.encode()
    resp.text = page
    resp.raise_for_status = MagicMock()
    with patch.object(c.client, "get", new_callable=AsyncMock) as get:
        get.return_value = resp
        items = await c.collect(_src("https://example.com/"))

    links = [item["link"] for item in items]
    assert links.count("https://example.com/") == 1
    await c.close()


@pytest.mark.asyncio
async def test_html_reader_rejects_private_ip():
    c = NativeHtmlReader()
    with pytest.raises(CollectionError) as exc:
        await c.collect(_src("http://127.0.0.1/"))
    assert exc.value.recoverable is False
    await c.close()


@pytest.mark.asyncio
async def test_html_reader_rejects_redirect_to_private_ip():
    """A private redirect target must be rejected before the second request."""
    c = NativeHtmlReader()
    resp = MagicMock()
    resp.status_code = 302
    resp.url = httpx.URL("https://example.com/redirect")
    resp.headers = {"location": "http://127.0.0.1/admin"}
    with patch.object(c.client, "get", new_callable=AsyncMock) as mg:
        mg.return_value = resp
        with pytest.raises(CollectionError) as exc:
            await c.collect(_src("https://example.com/redirect"))
    assert exc.value.recoverable is False
    assert mg.await_count == 1
    await c.close()


def test_html_reader_validate_url():
    c = NativeHtmlReader()
    assert c.validate_url("https://example.com/") is True
    assert c.validate_url("http://10.0.0.1/") is False


# ── Native Reddit subreddit collector ─────────────────────────────


REDDIT_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <title>r/AI_Agents</title>
 <entry>
  <id>t3_ab1</id>
  <title>New model</title>
  <link href="https://www.reddit.com/r/AI_Agents/comments/ab1/x"/>
  <updated>2026-07-01T00:00:00+00:00</updated>
 </entry>
 <entry>
  <id>t3_cd2</id>
  <title>Other</title>
  <link href="https://www.reddit.com/r/AI_Agents/comments/cd2/y"/>
  <updated>2026-07-02T00:00:00+00:00</updated>
 </entry>
</feed>"""


@pytest.mark.asyncio
async def test_reddit_parses_rss():
    c = NativeRedditSubredditCollector()
    resp = MagicMock()
    resp.status_code = 200
    resp.content = REDDIT_RSS.encode()
    resp.raise_for_status = MagicMock()
    with patch.object(c.client, "get", new_callable=AsyncMock) as mg:
        mg.return_value = resp
        items = await c.collect(_src("https://www.reddit.com/r/AI_Agents/", stype="reddit_subreddit"))
    assert len(items) == 2
    assert items[0]["post_id"] == "ab1"
    assert items[0]["subreddit"] == "ai_agents"
    assert items[0]["link"].startswith("https://www.reddit.com/")
    assert items[0]["type"] == "reddit_post"
    await c.close()


@pytest.mark.asyncio
async def test_reddit_rate_limit_is_recoverable():
    c = NativeRedditSubredditCollector()
    resp = MagicMock()
    resp.status_code = 429
    with patch.object(c.client, "get", new_callable=AsyncMock) as mg:
        mg.return_value = resp
        with pytest.raises(CollectionError) as exc:
            await c.collect(_src("https://www.reddit.com/r/ai/", stype="reddit_subreddit"))
    assert exc.value.recoverable is True
    await c.close()


@pytest.mark.asyncio
async def test_reddit_blocked_is_recoverable():
    c = NativeRedditSubredditCollector()
    resp = MagicMock()
    resp.status_code = 403
    with patch.object(c.client, "get", new_callable=AsyncMock) as mg:
        mg.return_value = resp
        with pytest.raises(CollectionError) as exc:
            await c.collect(_src("https://www.reddit.com/r/ai/", stype="reddit_subreddit"))
    assert exc.value.recoverable is True
    await c.close()


@pytest.mark.asyncio
async def test_reddit_requires_subreddit():
    c = NativeRedditSubredditCollector()
    with pytest.raises(CollectionError) as exc:
        await c.collect(_src("https://www.reddit.com/", stype="reddit_subreddit", cfg={}))
    assert exc.value.recoverable is False
    await c.close()


# ── Native YouTube RSS collector ─────────────────────────────────


YT_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
 <title>Fireship</title>
 <entry>
  <id>yt:video:AAAAA</id>
  <title>100s of lines of code</title>
  <link href="https://www.youtube.com/watch?v=AAAAA"/>
  <published>2026-07-01T00:00:00+00:00</published>
 </entry>
 <entry>
  <id>yt:video:BBBBB</id>
  <title>Second video</title>
  <link href="https://www.youtube.com/watch?v=BBBBB"/>
  <published>2026-07-02T00:00:00+00:00</published>
 </entry>
</feed>"""


@pytest.mark.asyncio
async def test_youtube_parses_rss_with_cached_channel_id():
    c = NativeYouTubeRssCollector()
    resp = MagicMock()
    resp.content = YT_FEED.encode()
    resp.raise_for_status = MagicMock()
    with patch.object(c.client, "get", new_callable=AsyncMock) as mg:
        mg.return_value = resp
        items = await c.collect(
            _src("https://www.youtube.com/@Fireship", stype="youtube_rss",
                 cfg={"channel_id": "UC123", "channel_handle": "Fireship"})
        )
    assert len(items) == 2
    assert items[0]["video_id"] == "AAAAA"
    assert items[0]["type"] == "youtube"
    assert items[0]["canonical_url"] == "https://www.youtube.com/watch?v=AAAAA"
    await c.close()


@pytest.mark.asyncio
async def test_youtube_resolves_handle_from_page():
    c = NativeYouTubeRssCollector()
    page_html = '<html><head><link rel="canonical" href="https://www.youtube.com/channel/UCsN12345678901234567890"/></head></html>'
    feed_resp = MagicMock()
    feed_resp.content = YT_FEED.encode()
    feed_resp.raise_for_status = MagicMock()
    page_resp = MagicMock()
    page_resp.text = page_html
    page_resp.raise_for_status = MagicMock()

    with patch.object(c.client, "get", new_callable=AsyncMock) as mg:
        mg.side_effect = [page_resp, feed_resp]
        items = await c.collect(
            _src("https://www.youtube.com/@Fireship", stype="youtube_rss", cfg={})
        )
    assert len(items) == 2
    await c.close()


@pytest.mark.asyncio
async def test_youtube_requires_handle():
    c = NativeYouTubeRssCollector()
    with pytest.raises(CollectionError) as exc:
        await c.collect(_src("https://www.youtube.com/", stype="youtube_rss", cfg={}))
    assert exc.value.recoverable is False
    await c.close()


def test_youtube_validate_url():
    c = NativeYouTubeRssCollector()
    assert c.validate_url("https://www.youtube.com/@Fireship") is True
    assert c.validate_url("https://example.com/") is False
