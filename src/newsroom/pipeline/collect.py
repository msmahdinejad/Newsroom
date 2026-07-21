"""Shared collection with cursors — used by CLI and full pipeline."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from newsroom.logging import get_logger
from newsroom.pipeline.cursors import (
    advance_cursor_from_items,
    filter_new_items,
    load_cursor,
    save_cursor,
)
from newsroom.sources.github import GitHubCollector
from newsroom.sources.html_reader import NativeHtmlReader
from newsroom.sources.reddit import NativeRedditSubredditCollector
from newsroom.sources.rss import RSSCollector
from newsroom.sources.telegram_collector import TelegramMTProtoCollector
from newsroom.sources.youtube_rss import NativeYouTubeRssCollector
from newsroom.storage.models import CollectionRun, RawItem, Source

logger = get_logger(__name__)

# Native (Agent-Reach-free) source types handled by this module.
NATIVE_SOURCE_TYPES: frozenset[str] = frozenset(
    {"rss", "github_releases", "telegram", "web_page", "reddit_subreddit", "youtube_rss"}
)


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
) -> dict[str, Any]:
    """Collect enabled sources, advance cursors only after persist success."""
    query = session.query(Source).filter(Source.enabled.is_(True))
    if source_type:
        query = query.filter(Source.type == source_type)
    sources = query.all()

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
        for source in sources:
            run = CollectionRun(
                source_id=source.id,
                started_at=datetime.now(UTC),
                status="running",
            )
            session.add(run)
            session.flush()

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
                        per_source.append({"source": source.name, "status": "skipped_mtproto_disabled"})
                        continue
                    items = await tg.collect(source)
                    # Telegram uses its own persist with edit handling
                    persist_stats = tg.persist_items(session, source, items)
                    # Gap detection
                    msg_ids = [it.get("message_id", 0) for it in items if it.get("message_id")]
                    gaps = tg.detect_gaps(session, source.id, msg_ids)

                    session.flush()
                    source.last_success_at = datetime.now(UTC)
                    source.consecutive_failures = 0
                    source.health_status = "healthy"
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
                    continue
                else:
                    run.status = "ok"
                    run.items_collected = 0
                    run.finished_at = datetime.now(UTC)
                    per_source.append({"source": source.name, "status": "skipped_type"})
                    continue

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
            except Exception as e:
                logger.error(f"collect failed {source.name}: {e}")
                failed.append(source.name)
                source.last_error_at = datetime.now(UTC)
                source.last_error = str(e)[:1000]
                source.consecutive_failures = (source.consecutive_failures or 0) + 1
                if source.consecutive_failures >= 3:
                    source.health_status = "degraded"
                run.status = "error"
                run.error = str(e)[:500]
                run.finished_at = datetime.now(UTC)
                # do not advance cursor
                per_source.append({"source": source.name, "status": "error", "error": str(e)[:120]})
    finally:
        await rss.close()
        await gh.close()
        await tg.close()

    return {
        "sources": len(sources),
        "new_items": total_new,
        "failed": failed,
        "detail": per_source,
    }
