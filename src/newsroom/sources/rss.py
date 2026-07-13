"""RSS and Atom feed collector."""

from datetime import datetime
from typing import Any

import feedparser
import httpx

from newsroom.config import settings
from newsroom.logging import get_logger
from newsroom.sources.base import CollectionError, SourceCollector

logger = get_logger(__name__)


class RSSCollector(SourceCollector):
    """Collect items from RSS/Atom feeds."""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.collection_timeout_connect,
                read=settings.collection_timeout_read,
                write=None,
                pool=None,
            ),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10),
        )

    async def collect(self, source_url: str) -> list[dict[str, Any]]:
        """Collect items from RSS/Atom feed.

        Args:
            source_url: Feed URL

        Returns:
            List of raw items (stored as JSON in database)

        Raises:
            CollectionError: On fetch/parse failures
        """
        try:
            logger.info(f"Fetching RSS feed: {source_url}")
            response = await self.client.get(source_url)
            response.raise_for_status()

            # Check size limit
            content_length = len(response.content)
            max_size = settings.collection_max_size_mb * 1024 * 1024
            if content_length > max_size:
                raise CollectionError(
                    f"Feed too large: {content_length} bytes (limit: {max_size})",
                    source_url,
                    recoverable=False,
                )

            # Parse feed
            feed = feedparser.parse(response.content)

            if feed.bozo and not feed.entries:
                # Feed is malformed and has no entries
                raise CollectionError(
                    f"Failed to parse feed: {feed.bozo_exception}",
                    source_url,
                    recoverable=False,
                )

            items = []
            for entry in feed.entries:
                raw_item = {
                    "type": "rss",
                    "source_url": source_url,
                    "entry_id": getattr(entry, "id", None),
                    "title": getattr(entry, "title", ""),
                    "link": getattr(entry, "link", ""),
                    "description": getattr(entry, "summary", ""),
                    "published": self._parse_published(entry),
                    "author": getattr(entry, "author", None),
                    "content": self._extract_content(entry),
                    "raw_entry": self._safe_dict(entry),
                }
                items.append(raw_item)

            logger.info(f"Collected {len(items)} items from {source_url}")
            return items

        except httpx.HTTPError as e:
            raise CollectionError(
                f"HTTP error: {e}",
                source_url,
                recoverable=True,
            ) from e
        except Exception as e:
            raise CollectionError(
                f"Unexpected error: {e}",
                source_url,
                recoverable=False,
            ) from e

    def validate_url(self, source_url: str) -> bool:
        """Check if URL looks like an RSS/Atom feed."""
        url_lower = source_url.lower()
        return (
            url_lower.startswith("http://")
            or url_lower.startswith("https://")
        ) and (
            url_lower.endswith(".xml")
            or url_lower.endswith(".rss")
            or url_lower.endswith(".atom")
            or "/feed" in url_lower
            or "/rss" in url_lower
            or "/atom" in url_lower
        )

    def _parse_published(self, entry) -> str | None:
        """Extract publication date."""
        for field in ["published_parsed", "updated_parsed"]:
            if hasattr(entry, field):
                time_struct = getattr(entry, field)
                if time_struct:
                    return datetime(*time_struct[:6]).isoformat()
        return None

    def _extract_content(self, entry) -> str:
        """Extract full content if available."""
        if hasattr(entry, "content") and entry.content:
            return entry.content[0].get("value", "")
        return getattr(entry, "summary", "")

    def _safe_dict(self, entry) -> dict[str, Any]:
        """Convert feedparser entry to safe dict (for JSON storage)."""
        # ponytail: minimal extraction, full preservation when JSON-safe
        result = {}
        for key in ["title", "link", "summary", "id", "author", "tags"]:
            if hasattr(entry, key):
                val = getattr(entry, key)
                if isinstance(val, (str, int, float, bool, type(None))):
                    result[key] = val
                elif isinstance(val, list):
                    result[key] = [str(item) for item in val]
                else:
                    result[key] = str(val)
        return result

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
