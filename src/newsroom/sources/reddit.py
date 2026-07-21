"""Native bounded Reddit subreddit collector — read-only, no Agent-Reach.

Reads a public subreddit's recent posts via Reddit's public JSON endpoint
(``https://www.reddit.com/r/{sub}/new.json``). No login state, no cookies,
no OAuth. Reddit serves public subreddit JSON to a descriptive User-Agent
without authentication, subject to rate limiting.

Guarantees:
  * bounded result count (<= 25 posts per fetch);
  * rate-limit awareness (HTTP 429 → retry-after, recoverable);
  * bounded timeouts and response size;
  * stable post identity (``t3_`` ID) — independent of title/handle;
  * content treated as data only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

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


class NativeRedditSubredditCollector(SourceCollector):
    """Collect recent public posts from a subreddit via Reddit JSON."""

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
                "User-Agent": f"{settings.collection_user_agent} (public subreddit reader)",
                "Accept": "application/json",
            },
        )

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        sub = _subreddit_from(source)
        url = f"{REDDIT_BASE}/r/{sub}/new.json?limit={MAX_POSTS}"
        try:
            response = await self.client.get(url)
            if response.status_code == 429:
                raise CollectionError("reddit rate limited (429)", source.url, recoverable=True)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise CollectionError(f"HTTP {e.response.status_code}", source.url, recoverable=True) from e
        except httpx.HTTPError as e:
            raise CollectionError(f"HTTP error: {e}", source.url, recoverable=True) from e

        max_size = settings.collection_max_size_mb * 1024 * 1024
        if len(response.content) > max_size:
            raise CollectionError("reddit response too large", source.url, recoverable=False)

        try:
            data = response.json()
        except Exception as e:
            raise CollectionError(f"non-JSON reddit response: {e}", source.url, recoverable=False) from e

        children = (
            data.get("data", {}).get("children", []) if isinstance(data, dict) else []
        )
        items: list[dict[str, Any]] = []
        for child in children[:MAX_POSTS]:
            post = child.get("data", {}) if isinstance(child, dict) else {}
            post_id = str(post.get("id") or "")
            if not post_id:
                continue
            created = float(post.get("created_utc") or 0)
            published = datetime.fromtimestamp(created, UTC).isoformat() if created else None
            permalink = post.get("permalink") or f"r/{sub}/comments/{post_id}"
            link = (
                f"https://www.reddit.com/{permalink.lstrip('/')}"
                if not permalink.startswith("http")
                else permalink
            )
            items.append(
                {
                    "type": "reddit_post",
                    "source_id": source.id,
                    "source_name": source.name,
                    "source_url": source.url,
                    "post_id": post_id,
                    "subreddit": sub,
                    "title": str(post.get("title") or "")[:500],
                    "description": str(post.get("selftext") or "")[:2000],
                    "link": link,
                    "canonical_url": link,
                    "published": published,
                    "score": int(post.get("score") or 0),
                    "num_comments": int(post.get("num_comments") or 0),
                    "author": str(post.get("author") or ""),
                    "is_self": bool(post.get("is_self")),
                    "collected_via": "native_reddit_json",
                }
            )
        logger.info(f"Reddit r/{sub}: {len(items)} posts")
        return items

    def validate_url(self, source_url: str) -> bool:
        p = urlparse(source_url)
        host = (p.hostname or "").lower()
        parts = [x for x in p.path.split("/") if x]
        return host in {"reddit.com", "www.reddit.com", "old.reddit.com"} and len(parts) >= 2

    async def close(self) -> None:
        await self.client.aclose()


__all__ = ["MAX_POSTS", "NativeRedditSubredditCollector"]
