"""Normalization pipeline - extract standard fields from raw items."""

import hashlib
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from newsroom.logging import get_logger

logger = get_logger(__name__)


class Normalizer:
    """Normalize raw items to standard format."""

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Extract standard fields from raw item.

        Args:
            raw_item: Raw item dict from collector

        Returns:
            Normalized item dict with standard fields
        """
        item_type = raw_item.get("type", "unknown")

        if item_type == "rss":
            return self._normalize_rss(raw_item)
        elif item_type == "github_releases":
            return self._normalize_github(raw_item)
        else:
            raise ValueError(f"Unknown item type: {item_type}")

    def _normalize_rss(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize RSS/Atom item."""
        title = raw_item.get("title", "").strip()
        description = raw_item.get("description", "").strip()
        source_url = raw_item.get("link", "")

        return {
            "title": title,
            "description": description,
            "source_url": source_url,
            "published_at": self._parse_timestamp(raw_item.get("published")),
            "content_hash": self._compute_hash(title, description),
            "normalized_url": self._normalize_url(source_url),
        }

    def _normalize_github(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize GitHub release item."""
        name = raw_item.get("name", "").strip()
        body = raw_item.get("body", "").strip()
        source_url = raw_item.get("html_url", "")

        # GitHub releases use tag_name as title fallback
        title = name or raw_item.get("tag_name", "")

        return {
            "title": title,
            "description": body,
            "source_url": source_url,
            "published_at": self._parse_timestamp(raw_item.get("published_at")),
            "content_hash": self._compute_hash(title, body),
            "normalized_url": self._normalize_url(source_url),
        }

    def _compute_hash(self, title: str, description: str) -> str:
        """Compute content hash for deduplication.

        Args:
            title: Item title
            description: Item description

        Returns:
            SHA-256 hex digest
        """
        # ponytail: deterministic, order matters
        content = f"{title}\n{description}".strip()
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication.

        Args:
            url: Source URL

        Returns:
            Normalized URL (lowercase domain, no tracking params)
        """
        if not url:
            return ""

        try:
            parsed = urlparse(url)

            # Check if URL has valid scheme and domain
            if not parsed.scheme or not parsed.netloc:
                return url  # Invalid URL, return as-is

            # Lowercase domain
            domain = parsed.netloc.lower()

            # Remove common tracking params
            # ponytail: minimal set, expand when needed
            tracking_params = {
                "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                "fbclid", "gclid", "msclkid",
                "ref", "source",
            }

            # Keep path and non-tracking params
            query_parts = []
            if parsed.query:
                for param in parsed.query.split("&"):
                    if "=" in param:
                        key = param.split("=", 1)[0]
                        if key not in tracking_params:
                            query_parts.append(param)

            query = "&".join(query_parts) if query_parts else ""

            # Rebuild URL
            normalized = f"{parsed.scheme}://{domain}{parsed.path}"
            if query:
                normalized += f"?{query}"

            return normalized

        except Exception as e:
            logger.warning(f"Failed to normalize URL {url}: {e}")
            return url

    def _parse_timestamp(self, timestamp: str | None) -> datetime | None:
        """Parse ISO timestamp string.

        Args:
            timestamp: ISO format timestamp or None

        Returns:
            datetime object or None
        """
        if not timestamp:
            return None

        try:
            # Handle ISO 8601 formats
            if timestamp.endswith("Z"):
                timestamp = timestamp[:-1] + "+00:00"
            return datetime.fromisoformat(timestamp)
        except Exception as e:
            logger.warning(f"Failed to parse timestamp {timestamp}: {e}")
            return None
