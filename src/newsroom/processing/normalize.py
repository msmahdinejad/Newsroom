"""Normalization pipeline — extract standard fields from raw items.

Uses proper JSON (not eval), deterministic SHA-256 hashes, URL canonicalization,
and Persian/Arabic character normalization.
"""

import hashlib
import html
import re
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

from newsroom.logging import get_logger

logger = get_logger(__name__)

# Persian/Arabic character normalization map
_PERSIAN_MAP = {
    "\u064a": "\u06cc",  # Arabic Yeh → Persian Yeh
    "\u0643": "\u06a9",  # Arabic Kaf → Persian Kaf
    "\u0623": "\u0627",
    "\u0625": "\u0627",
    "\u0622": "\u0627",
    "\u0629": "\u0647",
    "\u0624": "\u0648",
    "\u0626": "\u06cc",
    "\u06f0": "0", "\u06f1": "1", "\u06f2": "2", "\u06f3": "3", "\u06f4": "4",
    "\u06f5": "5", "\u06f6": "6", "\u06f7": "7", "\u06f8": "8", "\u06f9": "9",
}

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "ref", "source", "_ga", "mc_cid", "mc_eid",
}


class Normalizer:
    """Normalize raw items to standard format."""

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Extract standard fields from raw item dict (from JSONB)."""
        item_type = raw_item.get("type", "unknown")

        if item_type == "rss":
            return self._normalize_rss(raw_item)
        elif item_type == "github_releases":
            return self._normalize_github(raw_item)
        elif item_type == "telegram":
            return self._normalize_telegram(raw_item)
        elif item_type == "youtube":
            return self._normalize_youtube(raw_item)
        elif item_type == "web_page":
            return self._normalize_web_page(raw_item)
        elif item_type == "github_discovery":
            return self._normalize_github_discovery(raw_item)
        elif item_type == "x_post":
            return self._normalize_x_post(raw_item)
        elif item_type == "reddit_post":
            return self._normalize_reddit_post(raw_item)
        elif item_type == "linkedin_public":
            return self._normalize_linkedin_public(raw_item)
        else:
            raise ValueError(f"Unknown item type: {item_type}")

    def _normalize_rss(self, raw: dict[str, Any]) -> dict[str, Any]:
        title = self._normalize_text(raw.get("title", ""))
        description = self._normalize_text(raw.get("description", ""))
        source_url = raw.get("link", "")

        return {
            "title": title,
            "description": description,
            "source_url": source_url,
            "canonical_url": self._canonicalize_url(source_url),
            "published_at": self._parse_timestamp(raw.get("published")),
            "language": self._detect_language(title + " " + description),
            "content_hash": self._compute_hash(title, description),
            "url_hash": self._compute_hash(self._canonicalize_url(source_url)),
        }

    def _normalize_github(self, raw: dict[str, Any]) -> dict[str, Any]:
        name = self._normalize_text(raw.get("name", ""))
        body = self._normalize_text(raw.get("body", ""))
        source_url = raw.get("html_url", "")
        title = name or raw.get("tag_name", "")

        return {
            "title": title,
            "description": body,
            "source_url": source_url,
            "canonical_url": self._canonicalize_url(source_url),
            "published_at": self._parse_timestamp(raw.get("published_at")),
            "language": "en",
            "content_hash": self._compute_hash(title, body),
            "url_hash": self._compute_hash(self._canonicalize_url(source_url)),
        }

    def _normalize_telegram(self, raw: dict[str, Any]) -> dict[str, Any]:
        text = self._normalize_text(raw.get("text", raw.get("message", "")))
        channel = raw.get("channel_name", raw.get("source_name", ""))
        link = raw.get("link", "")

        # Use first 120 chars of text as title, or fallback to channel name
        title = text[:120] if text else f"Telegram post from {channel}"

        # Outbound links for richer normalization
        outbound = raw.get("outbound_links", [])
        if outbound and not link:
            link = outbound[0]

        return {
            "title": title,
            "description": text,
            "source_url": link,
            "canonical_url": link,
            "published_at": self._parse_timestamp(raw.get("date")),
            "language": self._detect_language(text),
            "content_hash": self._compute_hash(title, text),
            "url_hash": self._compute_hash(link) if link else self._compute_hash(title),
        }

    def _normalize_youtube(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a YouTube video metadata item.

        Identity is the stable video_id and channel_id, never the title.
        Published timestamp comes from yt-dlp's upload_date field.
        """
        video_id = str(raw.get("video_id") or "")
        channel_id = str(raw.get("channel_id") or "")
        title = self._normalize_text(raw.get("title", ""))
        description = self._normalize_text(raw.get("description", ""))
        canonical = raw.get("canonical_url") or f"https://www.youtube.com/watch?v={video_id}"

        # Dedup identity: video_id is stable globally; channel_id scopes it.
        return {
            "title": title,
            "description": description,
            "source_url": canonical,
            "canonical_url": self._canonicalize_url(canonical),
            "published_at": self._parse_timestamp(raw.get("published")),
            "language": self._detect_language(title + " " + description),
            "content_hash": self._compute_hash(f"yt:{video_id}:{channel_id}"),
            "url_hash": self._compute_hash(self._canonicalize_url(canonical)),
        }

    def _normalize_web_page(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a web-page read item. Source URL is the canonical identity."""
        title = self._normalize_text(raw.get("title", ""))
        description = self._normalize_text(raw.get("description", ""))
        source_url = raw.get("link") or raw.get("source_url") or ""

        return {
            "title": title or source_url,
            "description": description,
            "source_url": source_url,
            "canonical_url": self._canonicalize_url(source_url),
            "published_at": self._parse_timestamp(raw.get("published")),
            "language": self._detect_language(title + " " + description),
            "content_hash": self._compute_hash(source_url, title),
            "url_hash": self._compute_hash(self._canonicalize_url(source_url)),
        }

    def _normalize_github_discovery(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a GitHub repo-discovery item. Repo full_name is the identity."""
        full_name = str(raw.get("repo_full_name") or "")
        name = self._normalize_text(raw.get("name") or full_name)
        description = self._normalize_text(raw.get("description", ""))
        source_url = raw.get("url") or f"https://github.com/{full_name}"

        return {
            "title": name,
            "description": description,
            "source_url": source_url,
            "canonical_url": self._canonicalize_url(source_url),
            "published_at": None,  # discovery has no publication timestamp
            "language": "en",
            "content_hash": self._compute_hash(f"gh-disc:{full_name}"),
            "url_hash": self._compute_hash(self._canonicalize_url(source_url)),
        }

    def _normalize_x_post(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize an X/Twitter post item. post_id is the identity.

        Handles both the public-page reader (XPublicReadCollector) and the
        production timeline collector (XTimelineCollector). The timeline
        collector produces 'text', 'account_id', 'handle', 'post_kind', and
        optional 'quoted_tweet' fields.
        """
        post_id = str(raw.get("post_id") or "")
        # The timeline collector uses 'text'; the public-page reader uses
        # 'content' or 'description'. Prefer 'text' for timeline items.
        text = self._normalize_text(
            raw.get("text") or raw.get("content") or raw.get("description") or ""
        )
        source_url = raw.get("link") or raw.get("source_url") or raw.get("canonical_url") or ""
        title = text[:120] if text else f"X post {post_id}"

        # Identity: x + post_id — stable numeric post ID, never display name.
        # The account_id and handle are metadata, not part of the dedup identity.
        return {
            "title": title,
            "description": text,
            "source_url": source_url,
            "canonical_url": source_url,
            "published_at": self._parse_timestamp(raw.get("published")),
            "language": self._detect_language(text),
            "content_hash": self._compute_hash(f"x:{post_id}"),
            "url_hash": self._compute_hash(source_url) if source_url else self._compute_hash(f"x:{post_id}"),
        }

    def _normalize_reddit_post(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a Reddit public-post item. post_id is the identity."""
        post_id = str(raw.get("post_id") or "")
        subreddit = str(raw.get("subreddit") or "")
        title = self._normalize_text(raw.get("title", ""))
        text = self._normalize_text(
            self._strip_html(raw.get("content") or raw.get("description") or "")
        )
        source_url = raw.get("link") or raw.get("source_url") or ""
        title = title or text[:120] or f"Reddit post {post_id}"

        return {
            "title": title,
            "description": text,
            "source_url": source_url,
            "canonical_url": source_url,
            "published_at": self._parse_timestamp(raw.get("published")),
            "language": self._detect_language(text),
            "content_hash": self._compute_hash(f"reddit:{subreddit}:{post_id}"),
            "url_hash": self._compute_hash(source_url) if source_url else self._compute_hash(f"reddit:{post_id}"),
        }

    @staticmethod
    def _strip_html(value: str) -> str:
        """Convert syndication markup to bounded plain text."""
        without_tags = re.sub(r"<[^>]+>", " ", value)
        return html.unescape(without_tags)

    def _normalize_linkedin_public(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a LinkedIn public-page item. Source URL is the identity."""
        title = self._normalize_text(raw.get("title", ""))
        description = self._normalize_text(raw.get("description", ""))
        source_url = raw.get("link") or raw.get("source_url") or ""

        return {
            "title": title or source_url,
            "description": description,
            "source_url": source_url,
            "canonical_url": self._canonicalize_url(source_url),
            "published_at": self._parse_timestamp(raw.get("published")),
            "language": self._detect_language(title + " " + description),
            "content_hash": self._compute_hash(source_url, title),
            "url_hash": self._compute_hash(self._canonicalize_url(source_url)),
        }

    def _normalize_text(self, text: str) -> str:
        """Apply Persian/Arabic character normalization + whitespace cleanup."""
        if not text:
            return ""
        for arabic, persian in _PERSIAN_MAP.items():
            text = text.replace(arabic, persian)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _canonicalize_url(self, url: str) -> str:
        """Canonicalize URL: lowercase domain, strip tracking, remove fragments."""
        if not url:
            return ""
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return url

            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]

            # Remove tracking params, sort remaining
            params = [(k, v) for k, v in parse_qsl(parsed.query) if k not in _TRACKING_PARAMS]
            query = urlencode(sorted(params))

            path = parsed.path.rstrip("/")
            result = f"{parsed.scheme}://{domain}{path}"
            if query:
                result += f"?{query}"
            return result
        except Exception as e:
            logger.warning(f"URL normalize failed: {url}: {e}")
            return url

    def _compute_hash(self, *parts: str) -> str:
        """Deterministic SHA-256 hash of concatenated parts."""
        content = "\n".join(str(p).strip() for p in parts)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _parse_timestamp(self, ts: str | None) -> datetime | None:
        if not ts:
            return None
        try:
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            return datetime.fromisoformat(ts)
        except Exception as e:
            logger.warning(f"Timestamp parse failed: {ts}: {e}")
            return None

    def _detect_language(self, text: str) -> str:
        """Simple heuristic: Persian/Arabic range → fa, else en."""
        if not text:
            return "en"
        persian_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
        return "fa" if persian_chars > len(text) * 0.15 else "en"
