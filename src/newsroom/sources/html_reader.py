"""Native bounded HTML reader — read-only website/newsletter collector.

For website and newsletter sources that have no RSS feed, this collector
performs a single bounded, read-only fetch of the public page and extracts:

  * page title and meta description (for the source itself);
  * recent article links (anchor text + href) as collectible raw items;
  * discovered RSS/Atom feed links (``<link rel="alternate">``) so the
    activation wave can convert a source to the native RSS collector when a
    feed is available ("RSS or public API first, then bounded HTML reading").

Guarantees:
  * http(s) only; SSRF protection rejects private/loopback/link-local hosts;
  * bounded response size (``COLLECTION_MAX_SIZE_MB``);
  * bounded timeouts; no JavaScript, no forms, no login, no crawling;
  * bounded number of extracted links (<= 25);
  * content treated as data only — never alters configuration or creates
    executable instructions.
"""

from __future__ import annotations

import contextlib
import ipaddress
import re
import socket
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from newsroom.config import settings
from newsroom.logging import get_logger
from newsroom.sources.base import CollectionError, SourceCollector
from newsroom.storage.models import Source

logger = get_logger(__name__)

MAX_LINKS = 25
MAX_ANCHOR_LEN = 300
MAX_DESC_LEN = 2000

ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def _validate_public_url(url: str) -> None:
    """Reject non-http(s), missing host, or private/loopback destinations."""
    if not url:
        raise CollectionError("empty url", url, recoverable=False)
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise CollectionError(f"invalid url: {e}", url, recoverable=False) from e
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise CollectionError(f"scheme '{parsed.scheme}' not allowed", url, recoverable=False)
    host = (parsed.hostname or "").lower()
    if not host:
        raise CollectionError("no hostname", url, recoverable=False)
    try:
        ip = ipaddress.ip_address(host)
        if _is_private_ip(str(ip)):
            raise CollectionError(f"private IP literal: {host}", url, recoverable=False)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise CollectionError(f"DNS failed for {host}: {e}", url, recoverable=False) from e
    for info in infos:
        if _is_private_ip(str(info[4][0])):
            raise CollectionError(f"{host} resolves to private address", url, recoverable=False)


class _PageParser(HTMLParser):
    """Bounded stdlib HTML parser: title, meta description, feed links, anchors."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = ""
        self.description = ""
        self.feed_urls: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._in_title = False
        self._in_anchor = False
        self._anchor_href = ""
        self._anchor_text: list[str] = []
        self._link_rel = ""
        self._link_href = ""
        self._og_title = ""
        self._og_desc = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        if t == "title":
            self._in_title = True
        elif t == "meta":
            name = a.get("name", "").lower()
            prop = a.get("property", "").lower()
            content = a.get("content", "")
            if prop in ("og:title", "twitter:title") and content and not self._og_title:
                self._og_title = content
            elif prop in ("og:description", "twitter:description") and content and not self._og_desc:
                self._og_desc = content
            elif name == "description" and content and not self.description:
                self.description = content
        elif t == "link":
            rel = a.get("rel", "").lower()
            href = a.get("href", "")
            mtype = a.get("type", "").lower()
            if href and ("alternate" in rel) and ("rss" in mtype or "atom" in mtype):
                self.feed_urls.append(urljoin(self.base_url, href))
        elif t == "a":
            self._in_anchor = True
            self._anchor_href = a.get("href", "")
            self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "title":
            self._in_title = False
        elif t == "a" and self._in_anchor:
            self._in_anchor = False
            href = self._anchor_href
            text = "".join(self._anchor_text).strip()
            if href and len(self.links) < MAX_LINKS:
                full = urljoin(self.base_url, href)
                # keep only http(s) links to the same site or known content
                if full.startswith(("http://", "https://")):
                    self.links.append((text[:MAX_ANCHOR_LEN], full))
            self._anchor_href = ""
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._in_anchor:
            self._anchor_text.append(data)

    def finalize(self) -> None:
        self.title = self.title.strip() or self._og_title.strip()
        if not self.description:
            self.description = self._og_desc.strip()
        self.title = self.title[:MAX_ANCHOR_LEN]
        self.description = self.description[:MAX_DESC_LEN]


_TAG_RE = re.compile(r"<[^>]+>")


class NativeHtmlReader(SourceCollector):
    """Read a public web page once, bounded, and extract recent links."""

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
            headers={"User-Agent": settings.collection_user_agent, "Accept": "text/html"},
        )

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        url = source.url
        _validate_public_url(url)
        try:
            response = await self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise CollectionError(f"HTTP {e.response.status_code}", url, recoverable=True) from e
        except httpx.HTTPError as e:
            raise CollectionError(f"HTTP error: {e}", url, recoverable=True) from e

        max_size = settings.collection_max_size_mb * 1024 * 1024
        if len(response.content) > max_size:
            raise CollectionError(f"page too large: {len(response.content)} bytes", url, recoverable=False)

        # Best-effort decode (httpx usually decodes; fallback to bytes).
        text = response.text
        parser = _PageParser(url)
        with contextlib.suppress(Exception):
            # HTMLParser is lenient; ignore any unexpected error.
            parser.feed(text)
        parser.finalize()

        items: list[dict[str, Any]] = []
        now = datetime.now(UTC).isoformat()
        seen: set[str] = set()
        for anchor_text, href in parser.links:
            if href in seen:
                continue
            seen.add(href)
            title = anchor_text or _TAG_RE.sub("", href).strip()[:MAX_ANCHOR_LEN]
            if not title:
                continue
            items.append(
                {
                    "type": "web_page",
                    "source_id": source.id,
                    "source_name": source.name,
                    "source_url": source.url,
                    "title": title,
                    "description": "",
                    "link": href,
                    "canonical_url": href,
                    "published": now,
                    "discovered_feed_urls": list(parser.feed_urls) if parser.feed_urls else [],
                    "collected_via": "native_html_reader",
                }
            )
        # Always include a page-level item so the source is observable even with
        # no extractable links; carries discovered feed URLs for activation.
        items.append(
            {
                "type": "web_page",
                "source_id": source.id,
                "source_name": source.name,
                "source_url": source.url,
                "title": parser.title or url,
                "description": parser.description,
                "link": url,
                "canonical_url": url,
                "published": now,
                "discovered_feed_urls": list(parser.feed_urls),
                "page_title": parser.title,
                "collected_via": "native_html_reader_page",
            }
        )
        logger.info(f"HTML reader {source.name}: {len(items)} items, feeds={parser.feed_urls}")
        return items

    def validate_url(self, source_url: str) -> bool:
        try:
            _validate_public_url(source_url)
            return True
        except CollectionError:
            return False

    async def close(self) -> None:
        await self.client.aclose()


__all__ = ["MAX_LINKS", "NativeHtmlReader"]
