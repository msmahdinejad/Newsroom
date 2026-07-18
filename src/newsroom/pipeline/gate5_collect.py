"""Gate 5 collection — Agent-Reach-backed external sources.

Extends the existing collect pipeline with support for Agent-Reach-sourced
items (YouTube, web_page, github_discovery, x_post, reddit_post,
linkedin_public) while preserving the existing native collectors for RSS,
GitHub releases, and Telegram MTProto.

The existing ``newsroom.pipeline.collect.collect_sources`` remains the
canonical collector for non-Agent-Reach sources. This module handles the
Agent-Reach-specific source types via the controlled runner.

Flow:
  Source registry -> AgentReach capability resolver (channel allowlist)
    -> allowlisted platform adapter -> fixed upstream command (shell=False)
    -> bounded structured result -> Newsroom raw item

Newsroom owns: source config, cursors, retries, timeouts, normalization,
deduplication, persistence, health state, auditability, and security policy.
"""

from __future__ import annotations

import contextlib
import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from newsroom.config import settings
from newsroom.logging import get_logger
from newsroom.pipeline.cursors import (
    advance_cursor_from_items,
    filter_new_items,
    load_cursor,
    save_cursor,
)
from newsroom.sources.agent_reach.adapters import (
    GitHubDiscoveryCollector,
    LinkedInPublicReadCollector,
    RedditPublicReadCollector,
    SSRFError,
    WebPageReader,
    XPublicReadCollector,
    YouTubeCollector,
)
from newsroom.sources.agent_reach.runner import RunnerError
from newsroom.sources.base import CollectionError
from newsroom.storage.models import (
    AgentReachSourceState,
    RawItem,
    Source,
)

logger = get_logger(__name__)


# Source types managed by this module. The existing collect_sources() in
# newsroom.pipeline.collect continues to handle rss, github_releases, telegram.
AGENT_REACH_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "youtube",
        "web_page",
        "github_discovery",
        "x_post",
        "reddit_post",
        "linkedin_public",
    }
)


def agent_reach_raw_content_hash(item: dict[str, Any]) -> str:
    """Deterministic raw-content hash for Agent-Reach-sourced items.

    Uses the stable platform-native identity (video_id, post_id, repo full
    name, canonical URL) — never AI-generated titles or summaries.
    """
    item_type = item.get("type", "")
    if item_type == "youtube":
        video_id = str(item.get("video_id") or "")
        channel_id = str(item.get("channel_id") or "")
        return hashlib.sha256(f"yt:{video_id}:{channel_id}".encode()).hexdigest()
    if item_type == "x_post":
        post_id = str(item.get("post_id") or "")
        return hashlib.sha256(f"x:{post_id}".encode()).hexdigest()
    if item_type == "reddit_post":
        post_id = str(item.get("post_id") or "")
        subreddit = str(item.get("subreddit") or "")
        return hashlib.sha256(f"reddit:{subreddit}:{post_id}".encode()).hexdigest()
    if item_type == "github_discovery":
        full = str(item.get("repo_full_name") or "")
        return hashlib.sha256(f"gh-disc:{full}".encode()).hexdigest()
    # web_page and linkedin_public — source URL is the identity
    url = item.get("link") or item.get("source_url") or ""
    title = item.get("title") or ""
    return hashlib.sha256((url + title).encode()).hexdigest()


def _adapter_for(source_type: str):
    """Return the adapter for the given Agent-Reach source type."""
    if source_type == "youtube":
        return YouTubeCollector()
    if source_type == "web_page":
        return WebPageReader()
    if source_type == "github_discovery":
        return GitHubDiscoveryCollector()
    if source_type == "x_post":
        return XPublicReadCollector()
    if source_type == "reddit_post":
        return RedditPublicReadCollector()
    if source_type == "linkedin_public":
        return LinkedInPublicReadCollector()
    raise CollectionError(
        f"no Agent-Reach adapter for source type '{source_type}'",
        "",
        recoverable=False,
    )


def _ensure_source_state(
    session: Session,
    source: Source,
    *,
    channel: str,
    backend: str,
) -> AgentReachSourceState:
    """Get or create the per-source Agent-Reach state row."""
    state = (
        session.query(AgentReachSourceState)
        .filter_by(source_id=source.id)
        .first()
    )
    if state is None:
        state = AgentReachSourceState(
            source_id=source.id,
            channel=channel,
            backend=backend,
            health_status="configured",
        )
        session.add(state)
        session.flush()
    return state


def _update_state_success(
    state: AgentReachSourceState,
    items: list[dict[str, Any]],
    *,
    backend: str,
) -> None:
    """Update source state after a successful bounded read."""
    state.health_status = "healthy"
    state.last_collected_at = datetime.now(UTC)
    state.last_error_category = None
    state.retry_after = None
    state.backend = backend
    if items:
        last = items[-1]
        state.last_stable_item_id = str(
            last.get("video_id")
            or last.get("post_id")
            or last.get("repo_full_name")
            or ""
        )[:200]
        state.last_original_url = str(last.get("link") or last.get("source_url") or "")[:65000]
        pub = last.get("published")
        if pub:
            from datetime import datetime as _dt

            try:
                if isinstance(pub, str):
                    if pub.endswith("Z"):
                        pub = pub[:-1] + "+00:00"
                    state.last_publication_ts = _dt.fromisoformat(pub)
            except (ValueError, TypeError):
                pass
        # Raw content hash from the last item
        state.last_raw_content_hash = agent_reach_raw_content_hash(last)


def _update_state_failure(
    state: AgentReachSourceState,
    *,
    error_category: str,
) -> None:
    """Update source state after a failed bounded read."""
    state.health_status = "degraded" if state.health_status != "unavailable" else "unavailable"
    state.last_error_category = error_category


async def collect_agent_reach_sources(
    session: Session,
    *,
    source_type: str | None = None,
    limit_per_source: int = 10,
) -> dict[str, Any]:
    """Collect Agent-Reach-backed sources.

    Only sources whose type is in ``AGENT_REACH_SOURCE_TYPES`` are handled
    here. Other source types are left to the existing ``collect_sources``.

    Agent-Reach must be enabled and have a pinned version before any
    subprocess is launched. If disabled, this function is a no-op that
    returns ``status=disabled`` for every Agent-Reach source.
    """
    query = session.query(Source).filter(Source.enabled.is_(True))
    if source_type:
        query = query.filter(Source.type == source_type)
    sources = query.all()

    ar_sources = [s for s in sources if s.type in AGENT_REACH_SOURCE_TYPES]
    if not ar_sources:
        return {
            "sources": 0,
            "new_items": 0,
            "failed": [],
            "detail": [],
            "disabled": False,
        }

    if not settings.agent_reach_ready():
        # Agent-Reach disabled — record status and exit cleanly.
        return {
            "sources": len(ar_sources),
            "new_items": 0,
            "failed": [],
            "detail": [
                {"source": s.name, "status": "agent_reach_disabled"}
                for s in ar_sources
            ],
            "disabled": True,
        }

    total_new = 0
    failed: list[str] = []
    per_source: list[dict[str, Any]] = []

    # Channel allowlist — enforced before any subprocess launches.
    allowed_channels = settings.agent_reach_allowed_channels_set()

    for source in ar_sources:
        # Map source.type -> Agent-Reach channel name.
        channel = _channel_for_source_type(source.type)
        if channel is None:
            per_source.append({"source": source.name, "status": "skipped_unknown_type"})
            continue
        if channel not in allowed_channels:
            per_source.append(
                {
                    "source": source.name,
                    "status": "skipped_channel_not_allowed",
                    "channel": channel,
                }
            )
            continue

        adapter = _adapter_for(source.type)
        try:
            items = await adapter.collect(source)
        except CollectionError as e:
            logger.error(f"agent_reach collect failed {source.name}: {e}")
            failed.append(source.name)
            state = _ensure_source_state(session, source, channel=channel, backend="")
            _update_state_failure(state, error_category=e.__class__.__name__)
            source.last_error_at = datetime.now(UTC)
            source.last_error = str(e)[:1000]
            source.consecutive_failures = (source.consecutive_failures or 0) + 1
            if source.consecutive_failures >= 3:
                source.health_status = "degraded"
            per_source.append(
                {
                    "source": source.name,
                    "status": "error",
                    "error": str(e)[:120],
                    "channel": channel,
                }
            )
            continue
        except RunnerError as e:
            logger.error(f"agent_reach runner rejected {source.name}: {e}")
            failed.append(source.name)
            state = _ensure_source_state(session, source, channel=channel, backend="")
            _update_state_failure(state, error_category=e.category)
            per_source.append(
                {
                    "source": source.name,
                    "status": "runner_error",
                    "error_category": e.category,
                    "channel": channel,
                }
            )
            continue
        except SSRFError as e:
            logger.warning(f"agent_reach SSRF rejected {source.name}: {e}")
            failed.append(source.name)
            state = _ensure_source_state(session, source, channel=channel, backend="")
            _update_state_failure(state, error_category="ssrf")
            per_source.append(
                {
                    "source": source.name,
                    "status": "ssrf_rejected",
                    "channel": channel,
                }
            )
            continue
        finally:
            with contextlib.suppress(Exception):
                await adapter.close()

        # Cursor filter — drop items already covered by the cursor.
        cursor = load_cursor(session, source.id)
        candidates = filter_new_items(items, cursor, source_type=source.type)
        candidates = candidates[:limit_per_source]

        # Persist new items with content-hash dedup.
        new_count = 0
        persisted_payloads: list[dict[str, Any]] = []
        for item in candidates:
            raw_hash = agent_reach_raw_content_hash(item)
            existing = (
                session.query(RawItem)
                .filter(
                    RawItem.source_id == source.id,
                    RawItem.content_hash == raw_hash,
                )
                .first()
            )
            if existing:
                persisted_payloads.append(item)
                continue
            session.add(
                RawItem(
                    source_id=source.id,
                    raw_data=item,
                    content_hash=raw_hash,
                )
            )
            persisted_payloads.append(item)
            new_count += 1

        session.flush()

        # Advance cursor only after persist success.
        next_cursor = advance_cursor_from_items(
            cursor, persisted_payloads, source_type=source.type
        )
        save_cursor(session, source.id, next_cursor)
        session.flush()

        # Update source and Agent-Reach state.
        source.last_success_at = datetime.now(UTC)
        source.consecutive_failures = 0
        source.health_status = "healthy"
        state = _ensure_source_state(
            session, source, channel=channel, backend=_backend_for_source_type(source.type)
        )
        _update_state_success(state, persisted_payloads, backend=state.backend)

        total_new += new_count
        per_source.append(
            {
                "source": source.name,
                "status": "ok",
                "new": new_count,
                "fetched": len(items),
                "after_cursor": len(candidates),
                "channel": channel,
            }
        )

    return {
        "sources": len(ar_sources),
        "new_items": total_new,
        "failed": failed,
        "detail": per_source,
        "disabled": False,
    }


def _channel_for_source_type(source_type: str) -> str | None:
    """Map a Newsroom source.type to the Agent-Reach channel name."""
    return {
        "youtube": "youtube",
        "web_page": "web",
        "github_discovery": "github",
        "x_post": "x",
        "reddit_post": "reddit",
        "linkedin_public": "linkedin",
    }.get(source_type)


def _backend_for_source_type(source_type: str) -> str:
    """Default upstream backend for a given Agent-Reach source type."""
    return {
        "youtube": "yt-dlp",
        "web_page": "jina-reader",
        "github_discovery": "gh",
        "x_post": "jina-reader",
        "reddit_post": "jina-reader",
        "linkedin_public": "jina-reader",
    }.get(source_type, "")


__all__ = [
    "AGENT_REACH_SOURCE_TYPES",
    "agent_reach_raw_content_hash",
    "collect_agent_reach_sources",
]
