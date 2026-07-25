"""Shared collection with cursors — used by CLI and full pipeline."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from collections import deque
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from newsroom.logging import get_logger, redact
from newsroom.pipeline.cursors import (
    advance_cursor_from_items,
    filter_new_items,
    load_cursor,
    save_cursor,
)
from newsroom.pipeline.source_lock import acquire_source_collection_lock
from newsroom.sources.github import GitHubCollector
from newsroom.sources.html_reader import NativeHtmlReader
from newsroom.sources.reddit import NativeRedditSubredditCollector
from newsroom.sources.rss import RSSCollector
from newsroom.sources.telegram_collector import TelegramMTProtoCollector
from newsroom.sources.validation_sweep import safe_failure_category
from newsroom.sources.youtube_rss import NativeYouTubeRssCollector
from newsroom.storage.models import CollectionRun, RawItem, Source

logger = get_logger(__name__)


def _release_attempt_transaction(
    session: Session,
    source: Source,
    run: CollectionRun,
) -> tuple[int, bool]:
    """Commit the attempt start and detach stateless sources during I/O."""
    is_real_session = type(session).__module__.startswith("sqlalchemy.")
    if not is_real_session:
        return 0, False
    run_id = int(run.id)
    if source.type != "telegram":
        session.expunge(source)
        session.commit()
        return run_id, True
    session.commit()
    return run_id, False


def _resume_attempt(
    session: Session,
    source: Source,
    run: CollectionRun,
    run_id: int,
    detached: bool,
) -> tuple[Source, CollectionRun]:
    if not detached:
        return source, run
    attached_source = session.merge(source)
    attached_run = session.get(CollectionRun, run_id)
    if attached_run is None:
        raise RuntimeError(f"collection run {run_id} disappeared")
    return attached_source, attached_run

# Native (Agent-Reach-free) source types handled by this module.
NATIVE_SOURCE_TYPES: frozenset[str] = frozenset(
    {"rss", "github_releases", "telegram", "web_page", "reddit_subreddit", "youtube_rss"}
)


def _source_attempt_order(source: Source) -> tuple[int, datetime, int]:
    """Prefer never-attempted, then least-recently-attempted sources."""
    attempted_at = source.last_attempt_at
    if attempted_at is None:
        return (0, datetime.min.replace(tzinfo=UTC), source.id)
    if attempted_at.tzinfo is None:
        attempted_at = attempted_at.replace(tzinfo=UTC)
    return (1, attempted_at, source.id)


def _bounded_fair_sources(sources: list[Source], max_sources: int) -> list[Source]:
    """Take oldest attempts fairly, at most one source per type per round."""
    buckets: dict[str, deque[Source]] = {}
    for source in sorted(sources, key=_source_attempt_order):
        buckets.setdefault(source.type, deque()).append(source)

    selected: list[Source] = []
    while buckets and len(selected) < max_sources:
        source_types = sorted(
            buckets,
            key=lambda source_type: _source_attempt_order(buckets[source_type][0]),
        )
        for source_type in source_types:
            selected.append(buckets[source_type].popleft())
            if not buckets[source_type]:
                del buckets[source_type]
            if len(selected) >= max_sources:
                break
    return selected


def raw_content_hash(item: dict[str, Any]) -> str:
    item_url = item.get("link") or item.get("html_url") or ""
    title = item.get("title") or item.get("name") or ""
    itype = item.get("type", "")
    if itype == "telegram":
        # Telegram identity is channel_id:message_id — use that for hash
        channel_id = item.get("telegram_channel_id", 0)
        msg_id = item.get("message_id", 0)
        return hashlib.sha256(f"tg:{channel_id}:{msg_id}".encode()).hexdigest()
    if itype == "youtube" or itype == "youtube_rss":
        video_id = item.get("video_id") or ""
        channel_id = item.get("channel_id") or ""
        if video_id:
            return hashlib.sha256(f"yt:{video_id}:{channel_id}".encode()).hexdigest()
    if itype == "reddit_post":
        post_id = item.get("post_id") or ""
        subreddit = item.get("subreddit") or ""
        if post_id:
            return hashlib.sha256(f"reddit:{subreddit}:{post_id}".encode()).hexdigest()
    return hashlib.sha256((item_url + title).encode()).hexdigest()


async def collect_sources(
    session: Session,
    *,
    source_type: str | None = None,
    limit_per_source: int = 10,
    max_sources: int | None = None,
    source_spacing_seconds: float = 0.0,
    exclude_source_types: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """Collect enabled sources, advance cursors only after persist success.

    ``max_sources`` caps the number of sources processed in this pass (for
    bounded verification/soak runs); the remaining sources keep their state.
    """
    query = session.query(Source).filter(Source.enabled.is_(True))
    if source_type:
        query = query.filter(Source.type == source_type)
    sources = query.all()
    if exclude_source_types:
        sources = [source for source in sources if source.type not in exclude_source_types]
    if max_sources is not None:
        sources = _bounded_fair_sources(sources, max_sources)

    rss = RSSCollector()
    gh = GitHubCollector()
    tg = TelegramMTProtoCollector()
    html = NativeHtmlReader()
    reddit = NativeRedditSubredditCollector()
    yt = NativeYouTubeRssCollector()
    total_new = 0
    failed: list[str] = []
    per_source: list[dict[str, Any]] = []

    try:
        for source_index, source in enumerate(sources):
            if source_index and source_spacing_seconds > 0:
                await asyncio.sleep(source_spacing_seconds)
            attempt_at = datetime.now(UTC)
            source.last_attempt_at = attempt_at
            source.validation_status = "attempting"
            source.failure_category = None
            run = CollectionRun(
                source_id=source.id,
                started_at=attempt_at,
                status="running",
            )
            session.add(run)
            session.flush()
            run_id, detached = _release_attempt_transaction(session, source, run)

            try:
                if source.type == "rss":
                    items = await rss.collect(source)
                elif source.type == "github_releases":
                    items = await gh.collect(source)
                elif source.type == "web_page":
                    items = await html.collect(source)
                elif source.type == "reddit_subreddit":
                    items = await reddit.collect(source)
                elif source.type == "youtube_rss":
                    items = await yt.collect(source)
                elif source.type == "telegram":
                    if not tg.configured:
                        run.status = "ok"
                        run.items_collected = 0
                        run.finished_at = datetime.now(UTC)
                        source.validation_status = "unavailable"
                        source.failure_category = "mtproto_not_configured"
                        source.no_cursor_reason = "mtproto_not_configured"
                        per_source.append({"source": source.name, "status": "skipped_mtproto_disabled"})
                        session.commit()
                        continue
                    items = await tg.collect(source)
                    if type(session).__module__.startswith("sqlalchemy."):
                        source = session.merge(source)
                    # Telegram uses its own persist with edit handling
                    persist_stats = tg.persist_items(session, source, items)
                    # Gap detection
                    msg_ids = [it.get("message_id", 0) for it in items if it.get("message_id")]
                    gaps = tg.detect_gaps(session, source.id, msg_ids)

                    session.flush()
                    source.last_success_at = datetime.now(UTC)
                    source.consecutive_failures = 0
                    source.health_status = "healthy"
                    source.validation_status = "valid"
                    source.failure_category = None
                    source.no_cursor_reason = None
                    run.status = "ok"
                    run.items_collected = persist_stats["new"]
                    run.finished_at = datetime.now(UTC)
                    total_new += persist_stats["new"]
                    per_source.append({
                        "source": source.name,
                        "status": "ok",
                        "new": persist_stats["new"],
                        "updated": persist_stats["updated"],
                        "skipped": persist_stats["skipped"],
                        "gaps": len(gaps),
                        "fetched": len(items),
                    })
                    session.commit()
                    continue
                else:
                    source, run = _resume_attempt(session, source, run, run_id, detached)
                    run.status = "ok"
                    run.items_collected = 0
                    run.finished_at = datetime.now(UTC)
                    source.validation_status = "failed"
                    source.failure_category = "unsupported_source_type"
                    source.no_cursor_reason = "unsupported_source_type"
                    per_source.append({"source": source.name, "status": "skipped_type"})
                    session.commit()
                    continue

                source, run = _resume_attempt(session, source, run, run_id, detached)
                acquire_source_collection_lock(session, source.id)
                cursor = load_cursor(session, source.id)
                candidates = filter_new_items(items, cursor, source_type=source.type)
                # cap fetch window; overlap retained by cursor filter
                candidates = candidates[:limit_per_source]

                persisted_payloads: list[dict[str, Any]] = []
                new_count = 0
                for item in candidates:
                    raw_hash = raw_content_hash(item)
                    existing = (
                        session.query(RawItem)
                        .filter(
                            RawItem.source_id == source.id,
                            RawItem.content_hash == raw_hash,
                        )
                        .first()
                    )
                    if existing:
                        # still count as seen for cursor advance (overlap)
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

                # flush so persist failure is visible before cursor advance
                session.flush()
                next_cursor = advance_cursor_from_items(
                    cursor, persisted_payloads, source_type=source.type
                )
                save_cursor(session, source.id, next_cursor)
                session.flush()

                source.last_success_at = datetime.now(UTC)
                source.consecutive_failures = 0
                source.health_status = "healthy"
                source.validation_status = "valid"
                source.failure_category = None
                source.no_cursor_reason = None
                run.status = "ok"
                run.items_collected = new_count
                run.finished_at = datetime.now(UTC)
                total_new += new_count
                per_source.append(
                    {
                        "source": source.name,
                        "status": "ok",
                        "new": new_count,
                        "fetched": len(items),
                        "after_cursor": len(candidates),
                    }
                )
                session.commit()
            except Exception as e:
                if type(session).__module__.startswith("sqlalchemy."):
                    with contextlib.suppress(Exception):
                        session.rollback()
                source, run = _resume_attempt(session, source, run, run_id, detached)
                safe_error = redact(str(e))[:1000]
                logger.error(f"collect failed {source.name}: {safe_error}")
                failed.append(source.name)
                source.last_error_at = datetime.now(UTC)
                source.last_error = safe_error
                source.consecutive_failures = (source.consecutive_failures or 0) + 1
                source.validation_status = "failed"
                source.failure_category = safe_failure_category(safe_error)
                source.no_cursor_reason = "collection_failed_before_cursor"
                source.health_status = "degraded"
                run.status = "error"
                run.error = safe_error[:500]
                run.finished_at = datetime.now(UTC)
                # do not advance cursor
                per_source.append({"source": source.name, "status": "error", "error": safe_error[:120]})
                session.commit()
    finally:
        await rss.close()
        await gh.close()
        await tg.close()
        await html.close()
        await reddit.close()
        await yt.close()

    return {
        "sources": len(sources),
        "new_items": total_new,
        "failed": failed,
        "detail": per_source,
    }
