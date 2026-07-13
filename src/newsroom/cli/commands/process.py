"""CLI commands for processing pipeline."""

import argparse

from newsroom.logging import get_logger, setup_logging
from newsroom.processing.cluster import Clusterer
from newsroom.processing.dedupe import Deduplicator
from newsroom.processing.normalize import Normalizer
from newsroom.storage.database import get_db
from newsroom.storage.models import NormalizedItem, RawItem

logger = get_logger(__name__)


def normalize_command(args: argparse.Namespace) -> int:
    """Normalize raw items.

    Args:
        args: Parsed arguments

    Returns:
        Exit code
    """
    setup_logging()
    logger.info("Starting normalization")

    try:
        normalizer = Normalizer()

        with get_db() as db:
            # Get unprocessed raw items
            raw_items = db.query(RawItem).outerjoin(
                NormalizedItem, RawItem.id == NormalizedItem.raw_item_id
            ).filter(NormalizedItem.id == None).limit(args.limit).all()  # noqa: E711

            if not raw_items:
                print("No raw items to normalize")
                return 0

            logger.info(f"Normalizing {len(raw_items)} items")

            for raw in raw_items:
                try:
                    # Parse raw data
                    import ast
                    raw_data = ast.literal_eval(raw.raw_data)

                    normalized_data = normalizer.normalize(raw_data)

                    normalized_item = NormalizedItem(
                        raw_item_id=raw.id,
                        title=normalized_data["title"],
                        description=normalized_data.get("description"),
                        source_url=normalized_data["source_url"],
                        published_at=normalized_data.get("published_at"),
                        content_hash=normalized_data["content_hash"],
                        normalized_url=normalized_data["normalized_url"],
                    )
                    db.add(normalized_item)

                except Exception as e:
                    logger.error(f"Failed to normalize raw_item {raw.id}: {e}")
                    continue

            db.commit()
            print(f"✓ Normalized {len(raw_items)} items")
            return 0

    except Exception as e:
        logger.error(f"Normalization failed: {e}")
        print(f"✗ Normalization failed: {e}")
        return 1


def dedupe_command(args: argparse.Namespace) -> int:
    """Deduplicate normalized items.

    Args:
        args: Parsed arguments

    Returns:
        Exit code
    """
    setup_logging()
    logger.info("Starting deduplication")

    try:
        deduplicator = Deduplicator()

        with get_db() as db:
            # Get non-duplicate items
            items = db.query(NormalizedItem).filter(
                NormalizedItem.is_duplicate == False  # noqa: E712
            ).limit(args.limit).all()

            if not items:
                print("No items to deduplicate")
                return 0

            item_ids = [item.id for item in items]
            stats = deduplicator.deduplicate_batch(item_ids)

            print(f"✓ Checked {len(items)} items")
            print(f"  Marked {stats['duplicates_marked']} duplicates")
            return 0

    except Exception as e:
        logger.error(f"Deduplication failed: {e}")
        print(f"✗ Deduplication failed: {e}")
        return 1


def cluster_command(args: argparse.Namespace) -> int:
    """Cluster normalized items into stories.

    Args:
        args: Parsed arguments

    Returns:
        Exit code
    """
    setup_logging()
    logger.info("Starting clustering")

    try:
        clusterer = Clusterer()

        with get_db() as db:
            # Get non-duplicate items not yet in a story
            # ponytail: no story membership tracking yet, cluster all
            items = db.query(NormalizedItem).filter(
                NormalizedItem.is_duplicate == False  # noqa: E712
            ).limit(args.limit).all()

            if not items:
                print("No items to cluster")
                return 0

            item_ids = [item.id for item in items]
            stats = clusterer.cluster_items(item_ids)

            print(f"✓ Clustered {stats['items_clustered']} items")
            print(f"  Created {stats['stories_created']} stories")
            return 0

    except Exception as e:
        logger.error(f"Clustering failed: {e}")
        print(f"✗ Clustering failed: {e}")
        return 1
