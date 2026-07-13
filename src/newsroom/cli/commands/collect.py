"""CLI commands for collection."""

import argparse

from newsroom.logging import get_logger, setup_logging
from newsroom.sources.github import GitHubCollector
from newsroom.sources.rss import RSSCollector
from newsroom.storage.database import get_db
from newsroom.storage.models import RawItem, Source

logger = get_logger(__name__)


async def collect_command(args: argparse.Namespace) -> int:
    """Collect from all enabled sources or specific type.

    Args:
        args: Parsed arguments

    Returns:
        Exit code
    """
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
            failed_sources = []

            for source in sources:
                try:
                    items = await _collect_from_source(source)

                    # Store raw items
                    for item_data in items:
                        raw_item = RawItem(
                            source_id=source.id,
                            raw_data=str(item_data),  # JSON stored as string
                        )
                        db.add(raw_item)

                    db.commit()

                    # Update source health
                    from datetime import datetime
                    source.last_success_at = datetime.utcnow()
                    source.consecutive_failures = 0
                    db.commit()

                    total_collected += len(items)
                    logger.info(f"Collected {len(items)} items from {source.name}")

                except Exception as e:
                    logger.error(f"Failed to collect from {source.name}: {e}")
                    failed_sources.append(source.name)

                    # Update source error tracking
                    from datetime import datetime
                    source.last_error_at = datetime.utcnow()
                    source.last_error = str(e)[:1000]  # Truncate
                    source.consecutive_failures += 1
                    db.commit()

            print(f"✓ Collected {total_collected} items from {len(sources)} sources")

            if failed_sources:
                print(f"✗ Failed sources: {', '.join(failed_sources)}")
                return 1

            return 0

    except Exception as e:
        logger.error(f"Collection failed: {e}")
        print(f"✗ Collection failed: {e}")
        return 1


async def _collect_from_source(source: Source) -> list[dict]:
    """Collect from a single source.

    Args:
        source: Source instance

    Returns:
        List of raw items
    """
    if source.type == "rss":
        collector = RSSCollector()
        try:
            items = await collector.collect(source.url)
            return items
        finally:
            await collector.close()

    elif source.type == "github_releases":
        collector = GitHubCollector()
        try:
            items = await collector.collect(source.url)
            return items
        finally:
            await collector.close()

    else:
        raise ValueError(f"Unknown source type: {source.type}")
