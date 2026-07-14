"""Collection CLI command — V2."""

import argparse
from datetime import UTC, datetime

from newsroom.logging import get_logger, setup_logging
from newsroom.sources.github import GitHubCollector
from newsroom.sources.rss import RSSCollector
from newsroom.storage.database import get_db
from newsroom.storage.models import CollectionRun, RawItem, Source

logger = get_logger(__name__)


async def collect_command(args: argparse.Namespace) -> int:
    """Collect from all enabled sources."""
    setup_logging()
    logger.info("Starting collection")

    try:
        with get_db() as db:
            query = db.query(Source).filter(Source.enabled == True)  # noqa: E712
            if args.source_type:
                query = query.filter(Source.type == args.source_type)
            sources = query.all()
            logger.info(f"Found {len(sources)} enabled sources")

            total_collected = 0
            failed_sources: list[str] = []

            rss = RSSCollector()
            gh = GitHubCollector()

            for source in sources:
                run = CollectionRun(
                    source_id=source.id,
                    started_at=datetime.now(UTC),
                    status="running",
                )
                db.add(run)
                db.flush()

                try:
                    if source.type == "rss":
                        items = await rss.collect(source)
                    elif source.type == "github_releases":
                        items = await gh.collect(source)
                    else:
                        logger.warning(f"Unknown source type: {source.type}")
                        continue

                    for item in items[:10]:
                        import hashlib

                        item_url = item.get("link") or item.get("html_url") or ""
                        raw_hash = hashlib.sha256(
                            (item_url + item.get("title", "")).encode()
                        ).hexdigest()

                        existing = db.query(RawItem).filter(
                            RawItem.source_id == source.id,
                            RawItem.content_hash == raw_hash,
                        ).first()
                        if existing:
                            continue

                        raw = RawItem(
                            source_id=source.id,
                            raw_data=item,
                            content_hash=raw_hash,
                        )
                        db.add(raw)
                        total_collected += 1

                    source.last_success_at = datetime.now(UTC)
                    source.consecutive_failures = 0
                    source.health_status = "healthy"
                    run.status = "ok"
                    run.items_collected = len(items)
                    run.finished_at = datetime.now(UTC)

                except Exception as e:
                    logger.error(f"Failed: {source.name}: {e}")
                    failed_sources.append(source.name)
                    source.last_error_at = datetime.now(UTC)
                    source.last_error = str(e)[:1000]
                    source.consecutive_failures += 1
                    if source.consecutive_failures >= 3:
                        source.health_status = "degraded"
                    run.status = "error"
                    run.error = str(e)[:500]
                    run.finished_at = datetime.now(UTC)

            await rss.close()
            await gh.close()
            db.commit()

            print(f"OK: Collected {total_collected} items from {len(sources)} sources")
            if failed_sources:
                print(f"WARN: Failed sources: {', '.join(failed_sources)}")
            return 0

    except Exception as e:
        logger.error(f"Collection failed: {e}")
        print(f"FAIL: {e}")
        return 1
