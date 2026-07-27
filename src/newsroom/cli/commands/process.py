"""Processing pipeline CLI commands — V2."""

import argparse

from newsroom.logging import get_logger, setup_logging
from newsroom.storage.database import get_db
from newsroom.storage.models import NormalizedItem

logger = get_logger(__name__)


def process_command(args: argparse.Namespace) -> int:
    """Run processing pipeline stages."""
    setup_logging()

    if args.process_command == "all":
        return _run_all()
    elif args.process_command == "normalize":
        return _normalize()
    elif args.process_command == "dedupe":
        return _dedupe()
    elif args.process_command == "cluster":
        return _cluster()
    elif args.process_command == "repair-clusters":
        return _repair_clusters()
    else:
        print("Unknown process command")
        return 1


def _run_all() -> int:
    """Run normalize → dedupe → cluster → evidence."""
    rc = _normalize()
    if rc != 0:
        return rc
    rc = _dedupe()
    if rc != 0:
        return rc
    rc = _cluster()
    return rc


def _normalize() -> int:
    """Normalize raw items."""
    logger.info("Starting normalization")
    try:
        from newsroom.pipeline.processing_worker import process_pending_items

        result = process_pending_items()
        print(f"OK: Normalized {result.normalized} of {result.raw_seen} claimed items")
        return 0
    except Exception as e:
        logger.error(f"Normalization failed: {e}")
        print(f"FAIL: {e}")
        return 1


def _dedupe() -> int:
    """Deduplicate normalized items."""
    logger.info("Starting deduplication")
    try:
        from newsroom.processing.dedupe import Deduplicator

        deduper = Deduplicator()
        with get_db() as db:
            items = db.query(NormalizedItem).filter(
                NormalizedItem.is_duplicate == False  # noqa: E712
            ).all()

            if not items:
                print("No items to deduplicate")
                return 0

            stats = deduper.deduplicate_batch(db, [i.id for i in items])
            print(f"OK: Checked {len(items)}, marked {stats['duplicates_marked']} duplicates")
            return 0
    except Exception as e:
        logger.error(f"Dedup failed: {e}")
        print(f"FAIL: {e}")
        return 1


def _cluster() -> int:
    """Cluster normalized items into stories."""
    logger.info("Starting clustering")
    try:
        from newsroom.processing.cluster import Clusterer

        clusterer = Clusterer()
        with get_db() as db:
            items = db.query(NormalizedItem).filter(
                NormalizedItem.is_duplicate == False  # noqa: E712
            ).all()

            if not items:
                print("No items to cluster")
                return 0

            stats = clusterer.cluster_items(db, [i.id for i in items])
            print(f"OK: Clustered {stats['items_clustered']} items into {stats['stories_created']} stories")
            return 0
    except Exception as e:
        logger.error(f"Clustering failed: {e}")
        print(f"FAIL: {e}")
        return 1


def _repair_clusters() -> int:
    """Split legacy clusters using the corrected similarity contract."""
    logger.info("Starting legacy cluster repair")
    try:
        from newsroom.pipeline.lock import PipelineLock
        from newsroom.processing.cluster_repair import (
            renormalize_reddit_items,
            repair_polluted_story_clusters,
        )

        with PipelineLock(blocking=True), get_db() as db:
            reddit_fixed = renormalize_reddit_items(db)
            stats = repair_polluted_story_clusters(db)
        print(
            "OK: "
            f"{reddit_fixed} Reddit items normalized; "
            f"{stats.stories_split} polluted stories split into "
            f"{stats.stories_created} additional coherent stories"
        )
        return 0
    except Exception as e:
        logger.error(f"Cluster repair failed: {e}")
        print(f"FAIL: {e}")
        return 1
