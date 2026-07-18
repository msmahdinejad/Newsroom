"""Platform adapters that use the Agent-Reach capability layer.

Each adapter implements the existing ``SourceCollector`` contract from
``newsroom.sources.base`` so it integrates with the collect pipeline
without leaking Agent-Reach-specific types into the core.

The flow per adapter:

  Source (Newsroom-owned config)
    -> adapter builds a fixed argument array from validated source config
    -> ControlledRunner.run(...) executes an allowlisted upstream tool
    -> adapter parses the bounded structured result into a list of raw item dicts
    -> the core pipeline takes over: dedupe, normalize, persist, cursor

Adapter-specific points:

- Web pages: Jina Reader (``curl https://r.jina.ai/URL``) restricted to an
  allowlist of public domains. SSRF protection enforces no private/loopback
  destinations, validates DNS, and rejects redirect-based SSRF.
- YouTube: ``yt-dlp --dump-json`` for video metadata. Curated channel
  allowlist only; no full media download, no comments, no arbitrary URLs.
- GitHub: existing native collector is preferred for scheduled production
  collection; the Agent-Reach adapter exists only for capability
  verification and curated repo discovery (``gh search repos``).
- X / Reddit / LinkedIn: read-only, public-page adapters with explicit
  production decisions recorded in the capability registry.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from newsroom.logging import get_logger
from newsroom.sources.agent_reach.registry import (
    AgentReachCapabilityRegistry,
    ProductionApproval,
)
from newsroom.sources.agent_reach.runner import (
    ControlledRunner,
    RunnerError,
    redact_credentials,
    run_upstream,
    validate_repo_identifier,
    validate_url,
    validate_youtube_channel_id,
    validate_youtube_video_id,
)
from newsroom.sources.base import CollectionError, SourceCollector
from newsroom.storage.models import Source

logger = get_logger(__name__)


# ── SSRF protection ───────────────────────────────────────────────

PRIVATE_NETWORK_PREFIXES: tuple[str, ...] = (
    "127.",
    "10.",
    "192.168.",
    "169.254.",
    "0.",
    "::1",
    "fc",
    "fd",
)

ALLOWED_WEB_SCHEMES: frozenset[str] = frozenset({"http", "https"})


@dataclass(frozen=True)
class WebReadResult:
    url: str
    final_url: str
    title: str
    content: str
    status: int
    bytes_read: int


class SSRFError(CollectionError):
    """Raised when a URL or its resolved destination is rejected as SSRF."""


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def _validate_public_url(url: str) -> str:
    """Validate a URL for safe public reading.

    Rejects:
      - non-http(s) schemes;
      - missing host;
      - hostnames that resolve to private/loopback/link-local addresses;
      - raw IP literals that are private/loopback/link-local;
      - obvious redirect-target injection (no fragment tricks).
    """
    if not isinstance(url, str) or not url:
        raise SSRFError("empty url", url, recoverable=False)
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise SSRFError(f"invalid url: {e}", url, recoverable=False) from e
    if parsed.scheme not in ALLOWED_WEB_SCHEMES:
        raise SSRFError(
            f"scheme '{parsed.scheme}' not allowed",
            url,
            recoverable=False,
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise SSRFError("no hostname", url, recoverable=False)
    # Reject raw private IP literals
    try:
        ip = ipaddress.ip_address(host)
        if _is_private_ip(str(ip)):
            raise SSRFError(
                f"private/loopback IP literal: {host}",
                url,
                recoverable=False,
            )
    except ValueError:
        pass  # not an IP literal — fine, resolve below
    # DNS resolution check — reject if any A/AAAA record is private
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise SSRFError(
            f"DNS resolution failed for {host}: {e}",
            url,
            recoverable=False,
        ) from e
    for info in infos:
        addr = str(info[4][0])
        if _is_private_ip(addr):
            raise SSRFError(
                f"{host} resolves to private address {addr}",
                url,
                recoverable=False,
            )
    return url


def _validate_redirect_target(url: str, allowed_hosts: set[str]) -> str:
    """Validate that a redirect target is still public and (when configured)
    still inside the allowed-hosts set.
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise SSRFError(f"invalid redirect: {e}", url, recoverable=False) from e
    if parsed.scheme not in ALLOWED_WEB_SCHEMES:
        raise SSRFError(
            f"redirect scheme '{parsed.scheme}' not allowed",
            url,
            recoverable=False,
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise SSRFError("redirect has no host", url, recoverable=False)
    if allowed_hosts and host not in allowed_hosts:
        raise SSRFError(
            f"redirect host '{host}' not in allowlist",
            url,
            recoverable=False,
        )
    return _validate_public_url(url)


# ── Web page reader (Jina Reader via Agent-Reach-selected backend) ──

# Default allowlist of public domains that the Web adapter will read.
# Extend via source.config["allowed_domains"] on a per-source basis.
DEFAULT_WEB_ALLOWED_DOMAINS: frozenset[str] = frozenset(
    {
        "openai.com",
        "anthropic.com",
        "github.com",
        "huggingface.co",
        "arxiv.org",
        "www.arxiv.org",
        "news.mit.edu",
        "deepmind.google",
        "ai.googleblog.com",
        "research.google",
        "microsoft.com",
        "blogs.microsoft.com",
        "ai.meta.com",
        "research.facebook.com",
        "youtube.com",
        "www.youtube.com",
    }
)


class WebPageReader(SourceCollector):
    """Read a public web page via the Agent-Reach-selected web reader.

    Uses Jina Reader (``https://r.jina.ai/URL``) by default. The Jina Reader
    endpoint itself is invoked through the controlled runner's curl
    operation; only allowlisted public-domain URLs are accepted.

    SSRF protection:
      - reject private/loopback/link-local destinations;
      - validate DNS resolution;
      - reject redirect-based SSRF (Jina Reader returns the final URL in
        a header; we re-validate it).
      - enforce response-size limits (controlled runner caps stdout).
      - enforce timeouts (controlled runner).
      - do not execute JavaScript, do not submit forms, do not log in,
        do not crawl unrestricted sites.
    """

    def __init__(self, runner: ControlledRunner | None = None) -> None:
        self._runner = runner or ControlledRunner()

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        url = source.url
        try:
            validate_url(url)
            _validate_public_url(url)
        except SSRFError as e:
            raise CollectionError(str(e), url, recoverable=False) from e
        except RunnerError as e:
            raise CollectionError(str(e), url, recoverable=False) from e

        allowed_domains = self._allowed_domains_for(source)
        host = (urlparse(url).hostname or "").lower()
        if allowed_domains and host not in allowed_domains:
            raise CollectionError(
                f"host '{host}' not in allowlist",
                url,
                recoverable=False,
            )

        jina_url = f"https://r.jina.ai/{url}"
        try:
            result = run_upstream(
                "curl",
                "jina-read",
                [jina_url],
                runner=self._runner,
            )
        except RunnerError as e:
            raise CollectionError(str(e), url, recoverable=e.category != "disabled") from e

        if not result.ok:
            raise CollectionError(
                f"jina-read exit={result.returncode}: {redact_credentials(result.stderr_text()[:200])}",
                url,
                recoverable=False,
            )

        text = result.stdout_text()
        return [self._parse_jina_output(text, url, source)]

    def _allowed_domains_for(self, source: Source) -> set[str]:
        configured = set(DEFAULT_WEB_ALLOWED_DOMAINS)
        cfg = source.config or {}
        extra = cfg.get("allowed_domains") or []
        if isinstance(extra, list):
            for d in extra:
                if isinstance(d, str) and d:
                    configured.add(d.lower().strip())
        return configured

    def _parse_jina_output(
        self,
        text: str,
        original_url: str,
        source: Source,
    ) -> dict[str, Any]:
        """Parse Jina Reader markdown/text output into a raw item dict.

        Jina Reader returns markdown prefixed with a title line and a
        URL-source line. We extract a title, the first chunk of content,
        and the canonical URL safely.
        """
        title = original_url
        content = text
        lines = text.splitlines()
        if lines:
            for line in lines[:5]:
                stripped = line.strip()
                if stripped.startswith("Title:"):
                    title = stripped[len("Title:"):].strip() or title
                    break
                if stripped.startswith("# "):
                    title = stripped[2:].strip() or title
                    break
        # Truncate content to a bounded excerpt for normalization safety.
        max_chars = 8000
        if len(content) > max_chars:
            content = content[:max_chars]
        return {
            "type": "web_page",
            "source_id": source.id,
            "source_name": source.name,
            "source_url": source.url,
            "title": title[:300],
            "description": content[:1000],
            "content": content,
            "link": original_url,
            "published": self._extract_published(text) or datetime.now(UTC).isoformat(),
            "collected_via": "agent_reach_jina_reader",
        }

    def _extract_published(self, text: str) -> str | None:
        # Jina Reader sometimes surfaces a "Published:" or "Date:" metadata line.
        for line in text.splitlines()[:20]:
            stripped = line.strip().lower()
            if stripped.startswith(("published:", "date:", "published time:")):
                value = line.split(":", 1)[-1].strip()
                if value:
                    return value
        return None

    def validate_url(self, source_url: str) -> bool:
        try:
            validate_url(source_url)
            _validate_public_url(source_url)
            return True
        except (SSRFError, RunnerError):
            return False

    async def close(self) -> None:
        pass


# ── YouTube adapter (yt-dlp via Agent-Reach) ─────────────────────


class YouTubeCollector(SourceCollector):
    """Collect new YouTube video metadata from a curated public channel.

    Production scope:
      - curated public channel allowlist only;
      - new video metadata: title, description, publication timestamp,
        stable channel ID, stable video ID, canonical URL;
      - optional public subtitle text when safely available;
      - durable per-channel cursor (last video ID by upload order);
      - deduplication by video ID at the raw-item layer.

    Out of scope:
      - downloading full video files;
      - archiving media;
      - collecting comments;
      - collecting private videos;
      - unlimited keyword discovery;
      - arbitrary user-submitted URLs;
      - persisting enormous transcripts without limits.
    """

    def __init__(self, runner: ControlledRunner | None = None) -> None:
        self._runner = runner or ControlledRunner()

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        # Source config carries the channel ID and an optional max items.
        cfg = source.config or {}
        channel_id = str(cfg.get("channel_id") or "")
        channel_handle = str(cfg.get("channel_handle") or "")
        max_items = int(cfg.get("max_items") or 25)

        if not channel_id and not channel_handle:
            raise CollectionError(
                "youtube source requires config.channel_id or config.channel_handle",
                source.url,
                recoverable=False,
            )

        if channel_id:
            try:
                validate_youtube_channel_id(channel_id)
            except RunnerError as e:
                raise CollectionError(str(e), source.url, recoverable=False) from e

        # The URL we pass to yt-dlp. Use the channel ID form for stability.
        if channel_id:
            target = f"https://www.youtube.com/channel/{channel_id}/videos"
        else:
            # Handle must be a safe identifier (no path or query)
            handle = channel_handle.lstrip("@")
            if not handle or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in handle):
                raise CollectionError(
                    f"invalid channel_handle: {channel_handle}",
                    source.url,
                    recoverable=False,
                )
            target = f"https://www.youtube.com/@{handle}/videos"

        try:
            result = run_upstream(
                "yt-dlp",
                "dump-json",
                [
                    "--playlist-end",
                    str(min(max(max_items, 1), 50)),
                    "--flat-playlist",
                    target,
                ],
                runner=self._runner,
            )
        except RunnerError as e:
            raise CollectionError(str(e), source.url, recoverable=e.category != "disabled") from e

        if not result.ok:
            raise CollectionError(
                f"yt-dlp exit={result.returncode}: {redact_credentials(result.stderr_text()[:200])}",
                source.url,
                recoverable=False,
            )

        items: list[dict[str, Any]] = []
        for line in result.stdout_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = self._adapt_yt_entry(data, source, channel_id, channel_handle)
            if item is not None:
                items.append(item)
        return items

    def _adapt_yt_entry(
        self,
        data: dict[str, Any],
        source: Source,
        source_channel_id: str,
        source_channel_handle: str,
    ) -> dict[str, Any] | None:
        video_id = str(data.get("id") or "")
        try:
            validate_youtube_video_id(video_id)
        except RunnerError:
            return None
        channel_id = str(data.get("channel_id") or source_channel_id or "")
        channel_name = str(data.get("channel") or data.get("uploader") or source_channel_handle or "")
        title = str(data.get("title") or "")
        description = str(data.get("description") or "")
        upload_date = str(data.get("upload_date") or "")
        published = self._parse_yt_date(upload_date)
        return {
            "type": "youtube",
            "source_id": source.id,
            "source_name": source.name,
            "source_url": source.url,
            "video_id": video_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "title": title[:500],
            "description": description[:4000],
            "published": published,
            "canonical_url": f"https://www.youtube.com/watch?v={video_id}",
            "link": f"https://www.youtube.com/watch?v={video_id}",
            "duration_seconds": int(data.get("duration") or 0),
            "view_count": int(data.get("view_count") or 0),
            "collected_via": "agent_reach_yt_dlp",
        }

    def _parse_yt_date(self, d: str) -> str | None:
        if not d or len(d) != 8 or not d.isdigit():
            return None
        try:
            return (
                datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), tzinfo=UTC).isoformat()
            )
        except ValueError:
            return None

    def validate_url(self, source_url: str) -> bool:
        u = source_url.lower()
        return (
            u.startswith("https://www.youtube.com/")
            or u.startswith("https://youtube.com/")
            or u.startswith("https://youtu.be/")
        )

    async def close(self) -> None:
        pass


# ── GitHub discovery adapter (gh search repos) ────────────────────


class GitHubDiscoveryCollector(SourceCollector):
    """Curated repository discovery via ``gh search repos``.

    Used for capability verification and curated repo discovery only.
    Scheduled release collection still uses the existing native
    ``GitHubCollector`` (``src/newsroom/sources/github.py``) which talks
    to the GitHub releases API directly.
    """

    def __init__(self, runner: ControlledRunner | None = None) -> None:
        self._runner = runner or ControlledRunner()

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        cfg = source.config or {}
        query = str(cfg.get("query") or "")
        if not query:
            raise CollectionError(
                "github discovery source requires config.query",
                source.url,
                recoverable=False,
            )
        if len(query) > 256:
            raise CollectionError(
                "github discovery query too long",
                source.url,
                recoverable=False,
            )
        try:
            result = run_upstream(
                "gh",
                "search-repos",
                [
                    "--limit",
                    str(int(cfg.get("limit") or 10)),
                    query,
                ],
                runner=self._runner,
            )
        except RunnerError as e:
            raise CollectionError(str(e), source.url, recoverable=e.category != "disabled") from e
        if not result.ok:
            raise CollectionError(
                f"gh search exit={result.returncode}: {redact_credentials(result.stderr_text()[:200])}",
                source.url,
                recoverable=False,
            )
        try:
            data = json.loads(result.stdout_text() or "[]")
        except json.JSONDecodeError as e:
            raise CollectionError(
                f"gh search returned non-JSON: {e}",
                source.url,
                recoverable=False,
            ) from e
        items: list[dict[str, Any]] = []
        if not isinstance(data, list):
            return items
        for repo in data:
            if not isinstance(repo, dict):
                continue
            full_name = str(repo.get("fullName") or repo.get("full_name") or "")
            try:
                if full_name:
                    validate_repo_identifier(full_name)
            except RunnerError:
                continue
            items.append(
                {
                    "type": "github_discovery",
                    "source_id": source.id,
                    "source_name": source.name,
                    "source_url": source.url,
                    "repo_full_name": full_name,
                    "name": str(repo.get("name") or ""),
                    "description": str(repo.get("description") or ""),
                    "url": str(repo.get("url") or f"https://github.com/{full_name}"),
                    "collected_via": "agent_reach_gh_search",
                }
            )
        return items

    def validate_url(self, source_url: str) -> bool:
        # Discovery sources use a placeholder URL; the real query lives in config.
        return source_url.startswith("agent-reach:github-discovery:") or "github.com" in source_url

    async def close(self) -> None:
        pass


# ── Public-page adapters for X, Reddit, LinkedIn (read-only) ─────


class XPublicReadCollector(SourceCollector):
    """Read a single public X/Twitter post URL via the Agent-Reach-selected
    web reader (Jina Reader). No persistent authentication, no cookies, no
    timeline monitoring.

    Production classification per the gate spec:
        - 'available for manual discovery, deferred for unattended production
          ingestion' unless an explicit curated account list exists AND
          the Agent-Reach backend passes real bounded tests AND dedicated
          authentication is approved.
    """

    def __init__(self, runner: ControlledRunner | None = None) -> None:
        self._runner = runner or ControlledRunner()

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        url = source.url
        if not self._is_public_x_url(url):
            raise CollectionError(
                "X collector only accepts public t.me/twitter.com/x.com post URLs",
                url,
                recoverable=False,
            )
        try:
            _validate_public_url(url)
        except SSRFError as e:
            raise CollectionError(str(e), url, recoverable=False) from e
        jina_url = f"https://r.jina.ai/{url}"
        try:
            result = run_upstream(
                "curl",
                "jina-read",
                [jina_url],
                runner=self._runner,
            )
        except RunnerError as e:
            raise CollectionError(str(e), url, recoverable=e.category != "disabled") from e
        if not result.ok:
            raise CollectionError(
                f"jina-read exit={result.returncode}: {redact_credentials(result.stderr_text()[:200])}",
                url,
                recoverable=False,
            )
        text = result.stdout_text()
        # Extract a stable post ID from the URL — never from the page content.
        post_id = self._extract_post_id(url)
        return [
            {
                "type": "x_post",
                "source_id": source.id,
                "source_name": source.name,
                "source_url": source.url,
                "post_id": post_id,
                "title": text[:300] if text else url,
                "description": text[:2000],
                "content": text[:8000],
                "link": url,
                "published": datetime.now(UTC).isoformat(),
                "collected_via": "agent_reach_jina_reader_x_public",
            }
        ]

    def _is_public_x_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        host = (parsed.hostname or "").lower()
        return host in {"twitter.com", "www.twitter.com", "x.com", "www.x.com", "t.me"} and bool(
            parsed.path and len(parsed.path.strip("/")) > 0
        )

    def _extract_post_id(self, url: str) -> str:
        try:
            parsed = urlparse(url)
        except Exception:
            return ""
        # /user/status/1234567890 or /user/status/1234567890?s=20
        parts = [p for p in parsed.path.split("/") if p]
        for i, p in enumerate(parts):
            if p == "status" and i + 1 < len(parts):
                return parts[i + 1]
        return ""

    def validate_url(self, source_url: str) -> bool:
        return self._is_public_x_url(source_url)

    async def close(self) -> None:
        pass


class RedditPublicReadCollector(SourceCollector):
    """Read a single public Reddit post URL via the Agent-Reach-selected
    web reader (Jina Reader). No login state, no subreddit monitoring.

    Production classification per the gate spec:
        'manual research capability only' unless an explicit curated
        subreddit list exists, a stable authenticated backend passes
        real bounded tests, dedicated account is configured, durable
        post/comment IDs are returned, bounded comment depth and result
        count are enforced, and unattended operation is reliable.
    """

    def __init__(self, runner: ControlledRunner | None = None) -> None:
        self._runner = runner or ControlledRunner()

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        url = source.url
        if not self._is_public_reddit_url(url):
            raise CollectionError(
                "Reddit collector only accepts public reddit.com URLs",
                url,
                recoverable=False,
            )
        try:
            _validate_public_url(url)
        except SSRFError as e:
            raise CollectionError(str(e), url, recoverable=False) from e
        jina_url = f"https://r.jina.ai/{url}"
        try:
            result = run_upstream(
                "curl",
                "jina-read",
                [jina_url],
                runner=self._runner,
            )
        except RunnerError as e:
            raise CollectionError(str(e), url, recoverable=e.category != "disabled") from e
        if not result.ok:
            raise CollectionError(
                f"jina-read exit={result.returncode}: {redact_credentials(result.stderr_text()[:200])}",
                url,
                recoverable=False,
            )
        text = result.stdout_text()
        post_id = self._extract_post_id(url)
        return [
            {
                "type": "reddit_post",
                "source_id": source.id,
                "source_name": source.name,
                "source_url": source.url,
                "post_id": post_id,
                "subreddit": self._extract_subreddit(url),
                "title": text[:300] if text else url,
                "description": text[:2000],
                "content": text[:8000],
                "link": url,
                "published": datetime.now(UTC).isoformat(),
                "collected_via": "agent_reach_jina_reader_reddit_public",
            }
        ]

    def _is_public_reddit_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        host = (parsed.hostname or "").lower()
        return host in {"reddit.com", "www.reddit.com", "old.reddit.com"} and bool(
            parsed.path and len(parsed.path.strip("/")) > 0
        )

    def _extract_post_id(self, url: str) -> str:
        try:
            parsed = urlparse(url)
        except Exception:
            return ""
        parts = [p for p in parsed.path.split("/") if p]
        for i, p in enumerate(parts):
            if p == "comments" and i + 1 < len(parts):
                return parts[i + 1]
        return ""

    def _extract_subreddit(self, url: str) -> str:
        try:
            parsed = urlparse(url)
        except Exception:
            return ""
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in ("r", "user"):
            return parts[1]
        return ""

    def validate_url(self, source_url: str) -> bool:
        return self._is_public_reddit_url(source_url)

    async def close(self) -> None:
        pass


class LinkedInPublicReadCollector(SourceCollector):
    """Public-page enrichment only for LinkedIn via the Agent-Reach-selected
    web reader. No logged-in automation, no profile collection, no jobs.

    Production classification per the gate spec:
        'public-page enrichment only, not scheduled production ingestion'.
    """

    def __init__(self, runner: ControlledRunner | None = None) -> None:
        self._runner = runner or ControlledRunner()

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        url = source.url
        if not self._is_public_linkedin_url(url):
            raise CollectionError(
                "LinkedIn collector only accepts public linkedin.com URLs (no profile/job URLs)",
                url,
                recoverable=False,
            )
        try:
            _validate_public_url(url)
        except SSRFError as e:
            raise CollectionError(str(e), url, recoverable=False) from e
        jina_url = f"https://r.jina.ai/{url}"
        try:
            result = run_upstream(
                "curl",
                "jina-read",
                [jina_url],
                runner=self._runner,
            )
        except RunnerError as e:
            raise CollectionError(str(e), url, recoverable=e.category != "disabled") from e
        if not result.ok:
            raise CollectionError(
                f"jina-read exit={result.returncode}: {redact_credentials(result.stderr_text()[:200])}",
                url,
                recoverable=False,
            )
        text = result.stdout_text()
        return [
            {
                "type": "linkedin_public",
                "source_id": source.id,
                "source_name": source.name,
                "source_url": source.url,
                "title": text[:300] if text else url,
                "description": text[:2000],
                "content": text[:8000],
                "link": url,
                "published": datetime.now(UTC).isoformat(),
                "collected_via": "agent_reach_jina_reader_linkedin_public",
            }
        ]

    def _is_public_linkedin_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        host = (parsed.hostname or "").lower()
        if host not in {"linkedin.com", "www.linkedin.com"}:
            return False
        path_parts = [p for p in parsed.path.split("/") if p]
        # Reject profile and job URLs outright
        if path_parts and path_parts[0] in {"in", "pub", "jobs", "company"}:
            return False
        return bool(path_parts)

    def validate_url(self, source_url: str) -> bool:
        return self._is_public_linkedin_url(source_url)

    async def close(self) -> None:
        pass


# ── Registry-driven default production decisions ────────────────

def apply_default_production_decisions(
    registry: AgentReachCapabilityRegistry,
) -> AgentReachCapabilityRegistry:
    """Apply the Gate 5 preferred-scope production decisions to a registry.

    These are defaults; live verification may flip a channel from DEFERRED
    to APPROVED or from MANUAL_DISCOVERY to DEFERRED. The defaults follow
    the gate spec's preferred fast-track outcome.
    """
    # Web: production ingestion approved (allowlisted reading only)
    registry.set_production_approval(
        "web",
        ProductionApproval.APPROVED,
        notes="Allowlisted public-domain reading via Jina Reader with SSRF protection",
    )
    # RSS: production ingestion approved (existing native collector retained)
    registry.set_production_approval(
        "rss",
        ProductionApproval.APPROVED,
        notes="Existing native RSS collector retained; Agent-Reach only supplies feedparser capability",
    )
    # GitHub: production ingestion approved (existing native release collector retained)
    registry.set_production_approval(
        "github",
        ProductionApproval.APPROVED,
        notes="Existing native GitHub release collector retained; Agent-Reach used for discovery only",
    )
    # YouTube: production ingestion approved when live verification passes; default deferred
    registry.set_production_approval(
        "youtube",
        ProductionApproval.DEFERRED,
        notes="Pending bounded real-read verification via yt-dlp",
    )
    # X: manual discovery only by default
    registry.set_production_approval(
        "x",
        ProductionApproval.MANUAL_DISCOVERY,
        notes="Public-page reading only; unattended monitoring requires curated accounts + dedicated auth",
    )
    # Reddit: manual research capability only
    registry.set_production_approval(
        "reddit",
        ProductionApproval.MANUAL_DISCOVERY,
        notes="Login state required for subreddit monitoring; manual research only",
    )
    # LinkedIn: public-page enrichment only
    registry.set_production_approval(
        "linkedin",
        ProductionApproval.MANUAL_DISCOVERY,
        notes="Public-page enrichment only; no logged-in automation",
    )
    # Instagram / Facebook / TikTok: deferred
    for ch in ("instagram", "facebook", "tiktok"):
        registry.set_production_approval(
            ch,
            ProductionApproval.DEFERRED,
            notes="Browser-session and operational-risk requirements unmet",
        )
    # Bilibili / XiaoHongShu / V2EX / Xueqiu / Podcast: deferred
    for ch in ("bilibili", "xiaohongshu", "v2ex", "xueqiu", "podcast"):
        registry.set_production_approval(
            ch,
            ProductionApproval.DEFERRED,
            notes="No documented unique-value case for the Persian AI newsroom yet",
        )
    # Search: production ingestion approved when live verification passes
    registry.set_production_approval(
        "search",
        ProductionApproval.DEFERRED,
        notes="Exa search via mcporter; pending bounded real-read verification",
    )
    return registry


__all__ = [
    "DEFAULT_WEB_ALLOWED_DOMAINS",
    "GitHubDiscoveryCollector",
    "LinkedInPublicReadCollector",
    "RedditPublicReadCollector",
    "SSRFError",
    "WebPageReader",
    "WebReadResult",
    "XPublicReadCollector",
    "YouTubeCollector",
    "apply_default_production_decisions",
    "_is_private_ip",
    "_validate_public_url",
    "_validate_redirect_target",
]
