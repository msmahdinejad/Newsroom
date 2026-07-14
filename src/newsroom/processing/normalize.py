"""Normalization pipeline — extract standard fields from raw items.

Uses proper JSON (not eval), deterministic SHA-256 hashes, URL canonicalization,
and Persian/Arabic character normalization.
"""

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse, parse_qsl, urlencode

from newsroom.logging import get_logger

logger = get_logger(__name__)

# Persian/Arabic character normalization map
_PERSIAN_MAP = {
    "ي": "ی",  # Arabic Yeh → Persian Yeh
    "ك": "ک",  # Arabic Kaf → Persian Kaf
    "أ": "ا",
    "إ": "ا",
    "آ": "ا",
    "ة": "ه",
    "ؤ": "و",
    "ئ": "ی",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
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
        title = text[:120] if text else f"Telegram post from {channel}"

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
