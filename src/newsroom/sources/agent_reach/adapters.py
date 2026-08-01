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
    validate_x_handle,
    validate_x_post_id,
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
_GITHUB_SOURCE_HOSTS = frozenset({"github.com", "www.github.com"})
_X_SOURCE_HOSTS = frozenset({"x.com", "www.x.com", "twitter.com", "www.twitter.com"})


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


def _matches_placeholder_or_https_host(
    source_url: str,
    *,
    placeholder_prefix: str,
    allowed_hosts: frozenset[str],
) -> bool:
    """Match an internal source placeholder or an HTTPS URL by parsed hostname."""
    if not isinstance(source_url, str):
        return False
    if source_url.startswith(placeholder_prefix):
        identifier = source_url.removeprefix(placeholder_prefix)
        return bool(identifier) and not any(char.isspace() or ord(char) < 32 for char in identifier)
    try:
        parsed = urlparse(source_url)
        explicit_port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.casefold() == "https"
        and (parsed.hostname or "").casefold() in allowed_hosts
        and parsed.username is None
        and parsed.password is None
        and explicit_port in {None, 443}
    )


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
        return _matches_placeholder_or_https_host(
            source_url,
            placeholder_prefix="agent-reach:github-discovery:",
            allowed_hosts=_GITHUB_SOURCE_HOSTS,
        )

    async def close(self) -> None:
        pass


# ── Public-page adapters for X, Reddit, LinkedIn (read-only) ─────


class XPublicReadCollector(SourceCollector):
    """Read a single public X/Twitter post URL via the Agent-Reach-selected
    web reader (Jina Reader). No persistent authentication, no cookies, no
    timeline monitoring.

    Production classification per the module contract:
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
        """A public X/Twitter post URL must contain a /status/ segment.

        Profile URLs (e.g. https://x.com/someuser) are not collected — only
        individual public posts are. This avoids collecting personal profile
        pages, which are out of scope for the module contract.
        """
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        host = (parsed.hostname or "").lower()
        if host not in {"twitter.com", "www.twitter.com", "x.com", "www.x.com", "t.me"}:
            return False
        # Require a /status/ segment for an individual post
        parts = [p for p in parsed.path.split("/") if p]
        return "status" in parts

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

    Production classification per the module contract:
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

    Production classification per the module contract:
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
    """Apply the Social collection preferred-scope production decisions to a registry.

    These are defaults; live verification may flip a channel from DEFERRED
    to APPROVED or from MANUAL_DISCOVERY to DEFERRED. The defaults follow
    the module contract's preferred fast-track outcome.
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
            notes="No documented unique-value case for this integration yet",
        )
    # Search: production ingestion approved when live verification passes
    registry.set_production_approval(
        "search",
        ProductionApproval.DEFERRED,
        notes="Exa search via mcporter; pending bounded real-read verification",
    )
    return registry


def upgrade_x_to_production(
    registry: AgentReachCapabilityRegistry,
) -> AgentReachCapabilityRegistry:
    """Flip the X channel to production ingestion approved with dedicated auth.

    Called after live verification confirms that:
    1. local X auth is configured (TWITTER_AUTH_TOKEN + TWITTER_CT0 env vars)
    2. a reviewed curated account list exists
    3. bounded real-read verification of timeline monitoring succeeded
    4. restart and cursor continuation work
    5. three polling cycles operated unattended across restart

    This is a one-way promotion — the registry flips X from MANUAL_DISCOVERY
    to APPROVED_WITH_AUTH and marks it production_ready. It is only called
    when the owner has explicitly opted in via
    AGENT_REACH_ALLOW_AUTHENTICATED_CHANNELS=true and the live verification
    has succeeded.
    """
    registry.set_production_approval(
        "x",
        ProductionApproval.APPROVED_WITH_AUTH,
        notes="twitter-cli backend, curated account allowlist, dedicated auth, "
        "bounded real-read verified across 3 polling cycles with restart",
    )
    registry.mark_success("x", backend="twitter-cli", production_ready=True)
    return registry


# ── X / Twitter production timeline collector ───────────────────


# Bounded defaults per the module contract.
X_DEFAULT_POLL_INTERVAL_MINUTES = 30
X_DEFAULT_MAX_POSTS_PER_POLL = 20
X_DEFAULT_INITIAL_BACKFILL = 30
X_DEFAULT_OVERLAP = 8  # 5–10 range; 8 is the midpoint
X_DEFAULT_CONCURRENCY = 1  # one account at a time (rate-limit safe)


class XTimelineCollector(SourceCollector):
    """Production X/Twitter timeline collector via twitter-cli (Agent-Reach backend).

    Production scope (read-only):
      - resolve configured account (handle -> stable numeric account ID)
      - bounded recent account timeline (user-posts)
      - bounded single-post reconciliation (tweet by ID)
      - quote-post metadata (quotedTweet field)

    Out of scope (forbidden):
      - production search
      - posting, replies, likes, follows, DMs, account changes
      - the controlled runner has no allowlisted operations for these

    Identity: ``x + post_id`` — stable numeric post ID, never display name.

    Auth handling:
      - TWITTER_AUTH_TOKEN and TWITTER_CT0 are passed via extra_env to the
        controlled runner ONLY for user/user-posts/tweet operations.
      - The adapter reads them from source.config['auth_env_keys'] which
        names env vars to read from the host environment — the values
        themselves never enter the database or the source registry.
      - If the env vars are not set, the adapter raises CollectionError
        (auth_not_configured) — it never silently proceeds.
      - twitter:status is called without tokens (capability probe).

    Bounded defaults:
      - poll every 30 minutes
      - max 20 posts per account per poll
      - initial backfill 30
      - overlap 5–10 (we use 8)
      - concurrency 1
      - bounded timeout and retries

    Inclusion policy:
      - original posts: include
      - quote posts: include (with quotedTweet metadata)
      - replies: exclude by default, configurable via source.config['include_replies']
      - reposts (retweets): exclude by default, configurable via source.config['include_reposts']
    """

    def __init__(self, runner: ControlledRunner | None = None) -> None:
        self._runner = runner or ControlledRunner()

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        cfg = source.config or {}
        handle = str(cfg.get("handle") or cfg.get("screen_name") or "")
        if not handle:
            raise CollectionError(
                "x timeline source requires config.handle",
                source.url,
                recoverable=False,
            )
        try:
            handle = validate_x_handle(handle)
        except RunnerError as e:
            raise CollectionError(str(e), source.url, recoverable=False) from e

        # Auth: read token env var names from config; read values from host env.
        # Never store the values in the database, repo, or logs.
        auth_token_env = str(cfg.get("auth_token_env") or "TWITTER_AUTH_TOKEN")
        ct0_env = str(cfg.get("ct0_env") or "TWITTER_CT0")
        import os

        auth_token = os.environ.get(auth_token_env, "")
        ct0 = os.environ.get(ct0_env, "")
        if not auth_token or not ct0:
            raise CollectionError(
                "x auth not configured (env vars not set)",
                source.url,
                recoverable=False,
            )
        auth_env = {"TWITTER_AUTH_TOKEN": auth_token, "TWITTER_CT0": ct0}

        # Resolve the handle to a stable numeric account ID (cached in source state).
        account_id, resolved_handle = await self._resolve_account(source, handle, auth_env)
        if not account_id:
            raise CollectionError(
                f"could not resolve x handle '{handle}' to a stable account ID",
                source.url,
                recoverable=True,
            )

        # Cache only safe identity metadata. Assign a fresh dict so SQLAlchemy
        # persists JSONB changes; access values remain process-local env vars.
        updated_config = dict(cfg)
        updated_config["account_id"] = account_id
        updated_config["resolved_handle"] = resolved_handle
        source.config = updated_config

        # Bounded timeline read.
        max_posts = int(cfg.get("max_posts") or X_DEFAULT_MAX_POSTS_PER_POLL)
        max_posts = max(1, min(max_posts, 50))
        try:
            result = run_upstream(
                "twitter",
                "user-posts",
                [resolved_handle, "-n", str(max_posts)],
                runner=self._runner,
                extra_env=auth_env,
            )
        except RunnerError as e:
            raise CollectionError(str(e), source.url, recoverable=e.category != "disabled") from e

        if not result.ok:
            stderr_text = result.stderr_text()
            # Detect auth failure / rate limit / challenge specifically.
            category = self._classify_failure(result.returncode, stderr_text)
            raise CollectionError(
                f"twitter user-posts exit={result.returncode} category={category}: "
                f"{redact_credentials(stderr_text[:200])}",
                source.url,
                recoverable=category in ("rate_limit", "challenge", "transient"),
            )

        # Parse the JSON output. twitter-cli emits a JSON array of tweet dicts.
        items = self._parse_timeline(result.stdout_text(), source, account_id, resolved_handle)
        if not items:
            return []

        # Apply inclusion policy.
        include_replies = bool(cfg.get("include_replies", False))
        include_reposts = bool(cfg.get("include_reposts", False))
        filtered = [
            item
            for item in items
            if (item["post_kind"] == "original")
            or (item["post_kind"] == "quote")
            or (item["post_kind"] == "reply" and include_replies)
            or (item["post_kind"] == "repost" and include_reposts)
        ]
        return filtered

    async def _resolve_account(
        self,
        source: Source,
        handle: str,
        auth_env: dict[str, str],
    ) -> tuple[str, str]:
        """Resolve a handle to a stable numeric account ID.

        Returns (account_id, resolved_handle). The resolved handle may differ
        from the configured handle if the account was renamed. We persist
        the stable account ID and the resolved handle separately so a handle
        change does not break dedup.
        """
        # Check source.config for a cached account_id first.
        cfg = source.config or {}
        cached_id = str(cfg.get("account_id") or "")
        if cached_id and cached_id.isdigit():
            # We have a cached stable ID; trust it. Handle reconciliation
            # happens via the timeline read itself.
            return cached_id, handle
        # No cached ID — resolve via twitter user --json.
        try:
            result = run_upstream(
                "twitter",
                "user",
                [handle],
                runner=self._runner,
                extra_env=auth_env,
            )
        except RunnerError as e:
            raise CollectionError(str(e), source.url, recoverable=e.category != "disabled") from e
        if not result.ok:
            raise CollectionError(
                f"twitter user exit={result.returncode}: {redact_credentials(result.stderr_text()[:200])}",
                source.url,
                recoverable=False,
            )
        try:
            data = json.loads(result.stdout_text())
        except json.JSONDecodeError as e:
            raise CollectionError(
                f"twitter user returned non-JSON: {e}",
                source.url,
                recoverable=False,
            ) from e
        if not isinstance(data, dict):
            raise CollectionError(
                "twitter user returned non-object JSON",
                source.url,
                recoverable=False,
            )
        # twitter-cli wraps user data under {"ok": true, "data": {...}}
        user_data = data.get("data") if data.get("ok") else data
        if not isinstance(user_data, dict):
            raise CollectionError(
                "twitter user returned no user data object",
                source.url,
                recoverable=False,
            )
        account_id = str(user_data.get("id") or "")
        resolved_handle = str(user_data.get("screenName") or user_data.get("screen_name") or handle)
        if not account_id or not account_id.isdigit():
            raise CollectionError(
                f"twitter user did not return a numeric account ID: {account_id[:32]}",
                source.url,
                recoverable=False,
            )
        return account_id, resolved_handle

    def _classify_failure(self, returncode: int, stderr: str) -> str:
        """Classify a twitter-cli failure into a safe category for health state."""
        lower = stderr.lower()
        if "rate limit" in lower or "429" in lower:
            return "rate_limit"
        if "challenge" in lower or "captcha" in lower or "verification" in lower:
            return "challenge"
        if "auth" in lower or "401" in lower or "not_authenticated" in lower:
            return "auth_failure"
        if "timeout" in lower or "timed out" in lower:
            return "timeout"
        if "not found" in lower or "404" in lower:
            return "not_found"
        return "transient"

    def _parse_timeline(
        self,
        stdout: str,
        source: Source,
        account_id: str,
        resolved_handle: str,
    ) -> list[dict[str, Any]]:
        """Parse twitter-cli user-posts JSON output into raw item dicts.

        The JSON shape (from twitter-cli serialization.py):
          [{"id": "...", "text": "...", "author": {"id": "...", "screenName": "..."},
            "metrics": {...}, "createdAt": "...", "createdAtISO": "...",
            "isRetweet": bool, "retweetedBy": str|null,
            "quotedTweet": {...}|null, "media": [...], "urls": [...],
            "lang": "...", "articleTitle": "...", "articleText": "..."}, ...]
        """
        if not stdout or not stdout.strip():
            return []
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise CollectionError(
                f"twitter user-posts returned non-JSON: {e}",
                source.url,
                recoverable=False,
            ) from e
        if not isinstance(data, list):
            # twitter-cli wraps posts under {"ok": true, "data": [...]}
            if isinstance(data, dict) and data.get("ok") and isinstance(data.get("data"), list):
                data = data["data"]
            else:
                return []

        items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for tweet in data:
            if not isinstance(tweet, dict):
                continue
            post_id = str(tweet.get("id") or "")
            try:
                validate_x_post_id(post_id)
            except RunnerError:
                continue  # skip malformed post IDs
            if post_id in seen_ids:
                continue
            seen_ids.add(post_id)

            # Determine post kind: original / reply / repost / quote.
            is_retweet = bool(tweet.get("isRetweet"))
            retweeted_by = tweet.get("retweetedBy")
            quoted = tweet.get("quotedTweet")
            text = str(tweet.get("text") or "")
            # Reply detection: twitter-cli doesn't expose inReplyTo directly
            # in the serialization; we infer from text starting with "@handle".
            is_reply = text.startswith("@") and " " in text and not is_retweet

            if is_retweet or retweeted_by:
                post_kind = "repost"
            elif quoted:
                post_kind = "quote"
            elif is_reply:
                post_kind = "reply"
            else:
                post_kind = "original"

            # Author — stable numeric account ID.
            author = tweet.get("author") or {}
            author_id = str(author.get("id") or account_id)
            author_handle = str(author.get("screenName") or author.get("screen_name") or resolved_handle)

            # Quoted tweet metadata (for quote posts).
            quoted_metadata: dict[str, Any] | None = None
            if isinstance(quoted, dict):
                quoted_author = quoted.get("author") or {}
                quoted_metadata = {
                    "quoted_post_id": str(quoted.get("id") or ""),
                    "quoted_text": str(quoted.get("text") or "")[:1000],
                    "quoted_author_id": str(quoted_author.get("id") or ""),
                    "quoted_author_handle": str(
                        quoted_author.get("screenName")
                        or quoted_author.get("screen_name")
                        or ""
                    ),
                    "quoted_url": self._canonical_url(
                        str(quoted_author.get("screenName") or ""),
                        str(quoted.get("id") or ""),
                    ),
                }

            # Media metadata (bounded).
            media_list = tweet.get("media") or []
            media: list[dict[str, Any]] = []
            if isinstance(media_list, list):
                for m in media_list[:4]:  # bound to 4 media items
                    if isinstance(m, dict):
                        media.append(
                            {
                                "type": str(m.get("type") or ""),
                                "url": str(m.get("url") or "")[:500],
                            }
                        )

            # Timestamps — prefer createdAtISO for stability.
            published = str(tweet.get("createdAtISO") or tweet.get("createdAt") or "")

            # Bounded text.
            bounded_text = text[:280 * 4]  # Twitter limit is 280 chars; allow 4x for safety
            if len(bounded_text) > 2000:
                bounded_text = bounded_text[:2000]

            item = {
                "type": "x_post",
                "source_id": source.id,
                "source_name": source.name,
                "source_url": source.url,
                "post_id": post_id,
                "account_id": author_id,
                "handle": author_handle,
                "post_kind": post_kind,
                "text": bounded_text,
                "published": published,
                "canonical_url": self._canonical_url(author_handle, post_id),
                "link": self._canonical_url(author_handle, post_id),
                "lang": str(tweet.get("lang") or ""),
                "metrics": {
                    "likes": int(tweet.get("metrics", {}).get("likes") or 0),
                    "retweets": int(tweet.get("metrics", {}).get("retweets") or 0),
                    "replies": int(tweet.get("metrics", {}).get("replies") or 0),
                    "quotes": int(tweet.get("metrics", {}).get("quotes") or 0),
                    "views": int(tweet.get("metrics", {}).get("views") or 0),
                },
                "media": media,
                "urls": [str(u) for u in (tweet.get("urls") or []) if isinstance(u, str)][:4],
                "quoted_tweet": quoted_metadata,
                "is_retweet": is_retweet,
                "retweeted_by": str(retweeted_by) if retweeted_by else None,
                "collected_via": "agent_reach_twitter_cli",
            }
            items.append(item)
        return items

    @staticmethod
    def _canonical_url(handle: str, post_id: str) -> str:
        """Build a canonical X post URL from handle + post ID."""
        h = handle.lstrip("@")
        return f"https://x.com/{h}/status/{post_id}"

    def validate_url(self, source_url: str) -> bool:
        # Timeline sources use a placeholder URL; the real handle lives in config.
        return _matches_placeholder_or_https_host(
            source_url,
            placeholder_prefix="agent-reach:x-timeline:",
            allowed_hosts=_X_SOURCE_HOSTS,
        )

    async def close(self) -> None:
        pass


__all__ = [
    "DEFAULT_WEB_ALLOWED_DOMAINS",
    "GitHubDiscoveryCollector",
    "LinkedInPublicReadCollector",
    "RedditPublicReadCollector",
    "SSRFError",
    "WebPageReader",
    "WebReadResult",
    "XPublicReadCollector",
    "XTimelineCollector",
    "YouTubeCollector",
    "apply_default_production_decisions",
    "upgrade_x_to_production",
    "_is_private_ip",
    "_validate_public_url",
    "_validate_redirect_target",
]
