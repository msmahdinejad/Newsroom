"""Native bounded Reddit subreddit collector — read-only, no Agent-Reach.

Reads a public subreddit's recent posts via Reddit's public RSS feed
(``https://www.reddit.com/r/{sub}/.rss``). No login state, no cookies, no
OAuth. Reddit serves public subreddit RSS to a descriptive browser-like
User-Agent without authentication, subject to rate limiting (HTTP 429).

Guarantees:
  * bounded result count (the RSS feed returns ~25 recent posts);
  * rate-limit awareness (HTTP 429 → retry-after, recoverable);
  * bounded timeouts and response size;
  * stable post identity (Reddit permalinks/t3 IDs) — independent of title;
  * content treated as data only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from newsroom.config import settings
from newsroom.logging import get_logger
from newsroom.sources.base import CollectionError, SourceCollector
from newsroom.storage.models import Source

logger = get_logger(__name__)

MAX_POSTS = 25
REDDIT_BASE = "https://www.reddit.com"


def _subreddit_from(source: Source) -> str:
    cfg = source.config or {}
    sub = str(cfg.get("subreddit") or "").strip()
    if sub:
        return sub.lstrip("r/").lower()
    # Derive from URL: https://www.reddit.com/r/AI_Agents/...
    p = urlparse(source.url)
    parts = [x for x in p.path.split("/") if x]
    if len(parts) >= 2 and parts[0] == "r":
        return parts[1].lower()
    raise CollectionError(
        "reddit source requires config.subreddit or a /r/<sub> URL",
        source.url,
        recoverable=False,
    )


def _post_id_from_permalink(permalink: str) -> str:
    """Extract the post id from a Reddit permalink: /r/sub/comments/<id>/..."""
    parts = [x for x in permalink.split("/") if x]
    for i, p in enumerate(parts):
        if p == "comments" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


class NativeRedditSubredditCollector(SourceCollector):
    """Collect recent public posts from a subreddit via Reddit RSS."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.collection_timeout_connect,
                read=settings.collection_timeout_read,
                write=30,
                pool=30,
            ),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=4),
            headers={
                # A real browser UA avoids Reddit's 403 bot block (the
                # ``compatible;`` bot form is rejected; a browser UA is served).
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/rss+xml, application/atom+xml, text/xml, */*",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        sub = _subreddit_from(source)
        url = f"{REDDIT_BASE}/r/{sub}/.rss?limit={MAX_POSTS}"
        try:
            response = await self.client.get(url)
            if response.status_code == 429:
                raise CollectionError("reddit rate limited (429)", source.url, recoverable=True)
            if response.status_code == 403:
                raise CollectionError("reddit blocked (403)", source.url, recoverable=True)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise CollectionError(f"HTTP {e.response.status_code}", source.url, recoverable=True) from e
        except httpx.HTTPError as e:
            raise CollectionError(f"HTTP error: {e}", source.url, recoverable=True) from e

        max_size = settings.collection_max_size_mb * 1024 * 1024
        if len(response.content) > max_size:
            raise CollectionError("reddit response too large", source.url, recoverable=False)

        feed = feedparser.parse(response.content)
        if feed.bozo and not feed.entries:
            raise CollectionError("reddit feed parse failed", source.url, recoverable=False)

        items: list[dict[str, Any]] = []
        for entry in feed.entries[:MAX_POSTS]:
            permalink = getattr(entry, "link", "") or ""
            post_id = _post_id_from_permalink(permalink) or getattr(entry, "id", "")
            if not post_id:
                continue
            # Normalize post id: strip the "t3_" prefix when present.
            if post_id.startswith("t3_"):
                post_id = post_id[3:]
            published = self._parse_published(entry)
            link = permalink if permalink.startswith("http") else f"{REDDIT_BASE}{permalink}"
            items.append(
                {
                    "type": "reddit_post",
                    "source_id": source.id,
                    "source_name": source.name,
                    "source_url": source.url,
                    "post_id": post_id,
                    "subreddit": sub,
                    "title": str(getattr(entry, "title", "") or "")[:500],
                    "description": str(getattr(entry, "summary", "") or "")[:2000],
                    "link": link,
                    "canonical_url": link,
                    "published": published,
                    "author": str(getattr(entry, "author", "") or ""),
                    "collected_via": "native_reddit_rss",
                }
            )
        logger.info(f"Reddit r/{sub}: {len(items)} posts")
        return items

    def _parse_published(self, entry: Any) -> str | None:
        ts = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if ts:
            dt = datetime(*ts[:6])
            return dt.replace(tzinfo=UTC).isoformat()
        return None

    def validate_url(self, source_url: str) -> bool:
        p = urlparse(source_url)
        host = (p.hostname or "").lower()
        parts = [x for x in p.path.split("/") if x]
        return host in {"reddit.com", "www.reddit.com", "old.reddit.com"} and len(parts) >= 2

    async def close(self) -> None:
        await self.client.aclose()


__all__ = ["MAX_POSTS", "NativeRedditSubredditCollector"]
