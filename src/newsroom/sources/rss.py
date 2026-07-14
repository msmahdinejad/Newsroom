"""RSS and Atom feed collector."""

from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx

from newsroom.config import settings
from newsroom.logging import get_logger
from newsroom.sources.base import CollectionError, SourceCollector
from newsroom.storage.models import Source

logger = get_logger(__name__)


class RSSCollector(SourceCollector):
    """Collect items from RSS/Atom feeds."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.collection_timeout_connect,
                read=settings.collection_timeout_read,
                write=30,
                pool=30,
            ),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10),
            headers={"User-Agent": settings.collection_user_agent},
        )

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        """Collect items from RSS/Atom feed."""
        try:
            logger.info(f"Fetching RSS: {source.name}")
            response = await self.client.get(source.url)
            response.raise_for_status()

            max_size = settings.collection_max_size_mb * 1024 * 1024
            if len(response.content) > max_size:
                raise CollectionError(
                    f"Feed too large: {len(response.content)} bytes",
                    source.url,
                    recoverable=False,
                )

            feed = feedparser.parse(response.content)
            if feed.bozo and not feed.entries:
                raise CollectionError(
                    f"Parse failed: {feed.bozo_exception}",
                    source.url,
                    recoverable=False,
                )

            items = []
            for entry in feed.entries:
                item = {
                    "type": "rss",
                    "source_id": source.id,
                    "source_name": source.name,
                    "source_url": source.url,
                    "entry_id": getattr(entry, "id", ""),
                    "title": getattr(entry, "title", "").strip(),
                    "link": getattr(entry, "link", ""),
                    "description": getattr(entry, "summary", "").strip(),
                    "published": self._parse_published(entry),
                    "author": getattr(entry, "author", ""),
                    "content": self._extract_content(entry),
                }
                items.append(item)

            logger.info(f"Collected {len(items)} items from {source.name}")
            return items

        except httpx.HTTPStatusError as e:
            raise CollectionError(f"HTTP {e.response.status_code}", source.url, recoverable=True) from e
        except httpx.HTTPError as e:
            raise CollectionError(f"HTTP error: {e}", source.url, recoverable=True) from e
        except CollectionError:
            raise
        except Exception as e:
            raise CollectionError(f"Unexpected: {e}", source.url, recoverable=False) from e

    def validate_url(self, source_url: str) -> bool:
        u = source_url.lower()
        return u.startswith(("http://", "https://")) and (
            any(x in u for x in ("/feed", "/rss", "/atom", ".xml", ".rss", ".atom"))
            or "/posts/default" in u
        )

    def _parse_published(self, entry: Any) -> str | None:
        for field in ("published_parsed", "updated_parsed"):
            ts = getattr(entry, field, None)
            if ts:
                return datetime(*ts[:6], tzinfo=UTC).isoformat()
        return None

    def _extract_content(self, entry: Any) -> str:
        if hasattr(entry, "content") and entry.content:
            return entry.content[0].get("value", "")
        return getattr(entry, "summary", "")

    async def close(self) -> None:
        await self.client.aclose()
