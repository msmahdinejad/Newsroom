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
from newsroom.sources.rss import RSSCollector
from newsroom.storage.models import CollectionRun, RawItem, Source

logger = get_logger(__name__)


def raw_content_hash(item: dict[str, Any]) -> str:
    item_url = item.get("link") or item.get("html_url") or ""
    title = item.get("title") or item.get("name") or ""
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

    return {
        "sources": len(sources),
        "new_items": total_new,
        "failed": failed,
        "detail": per_source,
    }
