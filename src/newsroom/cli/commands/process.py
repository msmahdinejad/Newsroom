"""Processing pipeline CLI commands — V2."""

import argparse

from newsroom.logging import get_logger, setup_logging
from newsroom.storage.database import get_db
from newsroom.storage.models import NormalizedItem, RawItem

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
        from newsroom.processing.normalize import Normalizer

        normalizer = Normalizer()
        with get_db() as db:
            raw_items = (
                db.query(RawItem)
                .outerjoin(NormalizedItem, RawItem.id == NormalizedItem.raw_item_id)
                .filter(NormalizedItem.id == None)  # noqa: E711
                .limit(500)
                .all()
            )

            if not raw_items:
                print("No raw items to normalize")
                return 0

            count = 0
            for raw in raw_items:
                try:
                    norm_data = normalizer.normalize(raw.raw_data)
                    norm = NormalizedItem(
                        raw_item_id=raw.id,
                        title=norm_data["title"][:500],
                        description=norm_data.get("description", "")[:2000],
                        source_url=norm_data["source_url"],
                        canonical_url=norm_data.get("canonical_url", ""),
                        published_at=norm_data.get("published_at"),
                        language=norm_data.get("language"),
                        content_hash=norm_data["content_hash"],
                        url_hash=norm_data.get("url_hash", ""),
                    )
                    db.add(norm)
                    count += 1
                except Exception as e:
                    logger.error(f"Normalize raw {raw.id}: {e}")

            print(f"OK: Normalized {count} items")
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
