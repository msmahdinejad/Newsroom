"""Native bounded YouTube channel RSS collector — read-only, no Agent-Reach.

Collects recent video metadata from a public YouTube channel via the
official channel RSS feed (``https://www.youtube.com/feeds/videos.xml?
channel_id=UC...``). This is the "RSS or public API first" path: no
yt-dlp, no media download, no comments, no authentication.

Channel handle (``@Fireship``) is resolved to a stable channel ID once by
reading the public channel page and extracting the ``externalId`` /
``channelId`` from the HTML. The resolved channel ID is cached in
``source.config['channel_id']`` so subsequent polls skip resolution.

Guarantees:
  * bounded result count (the RSS feed returns ~15 recent videos);
  * stable video identity (``yt:video:VIDEOID``) — independent of title;
  * bounded timeouts and response size;
  * content treated as data only.
"""

from __future__ import annotations

import re
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

YOUTUBE_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
_CHANNEL_ID_RE = re.compile(r'"channelId":"(UC[\w-]{22})"')
_EXTERNAL_ID_RE = re.compile(r'"externalId":"(UC[\w-]{22})"')
_CANONICAL_RE = re.compile(r'<link[^>]+rel="canonical"[^>]+href="https://www\.youtube\.com/channel/(UC[\w-]{22})"')


class NativeYouTubeRssCollector(SourceCollector):
    """Collect recent videos from a public YouTube channel via RSS."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.collection_timeout_connect,
                read=settings.collection_timeout_read,
                write=30,
                pool=30,
            ),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=6),
            headers={
                # RSS feed fetch works with any UA. The handle->channel_id
                # resolution step uses a crawler UA that YouTube serves to
                # without the EU consent wall (browser UAs are gated behind a
                # consent redirect). Read-only public channel metadata only.
                "User-Agent": "Mozilla/5.0 (compatible; newsroom/2.0; +https://github.com/newsroom)",
                "Accept": "text/html,application/atom+xml,application/xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    async def _resolve_channel(self, source: Source) -> tuple[str, str]:
        """Resolve a handle/@handle/c/channel URL to a stable channel ID.

        Uses a crawler User-Agent for the channel-page fetch because YouTube
        gates browser UAs behind an EU consent redirect that hides the
        channel ID. The resolved channel ID is cached in source.config.
        """
        cfg = source.config or {}
        handle = str(cfg.get("channel_handle") or "").lstrip("@").strip()
        channel_id_cfg = str(cfg.get("channel_id") or "").strip()
        if channel_id_cfg:
            return channel_id_cfg, handle
        url = source.url
        p = urlparse(url)
        parts = [x for x in p.path.split("/") if x]
        if not handle and parts:
            if parts[0].startswith("@"):
                handle = parts[0].lstrip("@")
            elif parts[0] == "channel" and len(parts) > 1:
                return parts[1], handle
        if not handle:
            raise CollectionError("youtube source requires config.channel_handle or a /@handle URL", source.url, recoverable=False)

        page_url = f"https://www.youtube.com/@{handle}"
        # Crawler UA bypasses the EU consent redirect (read-only public metadata).
        try:
            response = await self.client.get(
                page_url, headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"}
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise CollectionError(f"youtube resolve failed: {e}", source.url, recoverable=True) from e

        html = response.text
        for rx in (_CHANNEL_ID_RE, _EXTERNAL_ID_RE, _CANONICAL_RE):
            m = rx.search(html)
            if m:
                return m.group(1), handle
        raise CollectionError(f"could not find channel ID for @{handle}", source.url, recoverable=True)

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        cfg = source.config or {}
        channel_id = str(cfg.get("channel_id") or "")
        handle = str(cfg.get("channel_handle") or "")
        if not channel_id:
            channel_id, handle = await self._resolve_channel(source)
            if not channel_id:
                raise CollectionError("could not resolve YouTube channel ID", source.url, recoverable=True)

        feed_url = YOUTUBE_FEED.format(cid=channel_id)
        try:
            response = await self.client.get(feed_url)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise CollectionError(f"HTTP {e.response.status_code}", source.url, recoverable=True) from e
        except httpx.HTTPError as e:
            raise CollectionError(f"HTTP error: {e}", source.url, recoverable=True) from e

        max_size = settings.collection_max_size_mb * 1024 * 1024
        if len(response.content) > max_size:
            raise CollectionError("youtube feed too large", source.url, recoverable=False)

        feed = feedparser.parse(response.content)
        if feed.bozo and not feed.entries:
            raise CollectionError("youtube feed parse failed", source.url, recoverable=False)

        items: list[dict[str, Any]] = []
        for entry in feed.entries:
            video_id = ""
            entry_id = getattr(entry, "id", "") or ""
            # yt:video:VIDEOID
            if entry_id.startswith("yt:video:"):
                video_id = entry_id[len("yt:video:"):]
            elif hasattr(entry, "link"):
                m = re.search(r"(?:v=|youtu\.be/|embed/)([\w-]{11})", entry.link or "")
                video_id = m.group(1) if m else ""
            if not video_id:
                continue
            published = self._parse_published(entry)
            items.append(
                {
                    "type": "youtube",
                    "source_id": source.id,
                    "source_name": source.name,
                    "source_url": source.url,
                    "video_id": video_id,
                    "channel_id": channel_id,
                    "channel_handle": handle,
                    "title": str(getattr(entry, "title", "") or "")[:500],
                    "description": str(getattr(entry, "summary", "") or "")[:2000],
                    "link": f"https://www.youtube.com/watch?v={video_id}",
                    "canonical_url": f"https://www.youtube.com/watch?v={video_id}",
                    "published": published,
                    "author": str(getattr(entry, "author", "") or ""),
                    "collected_via": "native_youtube_rss",
                }
            )
        logger.info(f"YouTube {source.name}: {len(items)} videos (channel {channel_id})")
        return items

    def _parse_published(self, entry: Any) -> str | None:
        ts = getattr(entry, "published_parsed", None)
        if ts:
            dt = datetime(*ts[:6])
            return dt.replace(tzinfo=UTC).isoformat()
        return None

    def validate_url(self, source_url: str) -> bool:
        u = source_url.lower()
        return (
            u.startswith("https://www.youtube.com/")
            or u.startswith("https://youtube.com/")
            or u.startswith("https://youtu.be/")
        )

    async def close(self) -> None:
        await self.client.aclose()


__all__ = ["NativeYouTubeRssCollector"]
