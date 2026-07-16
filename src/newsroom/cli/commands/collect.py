"""Collection CLI — uses shared cursor-aware collector."""

import argparse

from newsroom.logging import get_logger, setup_logging
from newsroom.pipeline.collect import collect_sources
from newsroom.storage.database import get_db

logger = get_logger(__name__)


async def collect_command(args: argparse.Namespace) -> int:
    setup_logging()
    logger.info("Starting collection")
    try:
        with get_db() as db:
            stats = await collect_sources(db, source_type=args.source_type)
            print(
                f"OK: Collected {stats['new_items']} new items from {stats['sources']} sources"
            )
            if stats["failed"]:
                print(f"WARN: Failed sources: {', '.join(stats['failed'])}")
            return 0
    except Exception as e:
        logger.error(f"Collection failed: {e}")
        print(f"FAIL: {e}")
        return 1
