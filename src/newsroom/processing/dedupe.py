"""Deduplication pipeline - mark duplicate items."""

from newsroom.logging import get_logger
from newsroom.storage.database import get_db
from newsroom.storage.models import NormalizedItem

logger = get_logger(__name__)


class Deduplicator:
    """Detect and mark duplicate normalized items."""

    def deduplicate_batch(self, item_ids: list[int]) -> dict[str, int]:
        """Mark duplicates in a batch of normalized items.

        Args:
            item_ids: List of normalized_item IDs to check

        Returns:
            Stats dict: {duplicates_marked, exact_hash, url_match}
        """
        stats = {
            "duplicates_marked": 0,
            "exact_hash": 0,
            "url_match": 0,
        }

        with get_db() as db:
            items = db.query(NormalizedItem).filter(
                NormalizedItem.id.in_(item_ids),
                NormalizedItem.is_duplicate == False,  # noqa: E712
            ).all()

            for item in items:
                if self._mark_if_duplicate(db, item):
                    stats["duplicates_marked"] += 1

            db.commit()

        return stats

    def _mark_if_duplicate(self, db, item: NormalizedItem) -> bool:
        """Check and mark item as duplicate if match found.

        Args:
            db: Database session
            item: Normalized item to check

        Returns:
            True if marked as duplicate
        """
        # Stage 1: Exact content hash match
        hash_duplicate = db.query(NormalizedItem).filter(
            NormalizedItem.content_hash == item.content_hash,
            NormalizedItem.id < item.id,  # Older item wins
            NormalizedItem.is_duplicate == False,  # noqa: E712
        ).first()

        if hash_duplicate:
            logger.info(
                f"Marking item {item.id} as duplicate of {hash_duplicate.id} (hash match)"
            )
            item.is_duplicate = True
            item.duplicate_of_id = hash_duplicate.id
            return True

        # Stage 2: Normalized URL match
        url_duplicate = db.query(NormalizedItem).filter(
            NormalizedItem.normalized_url == item.normalized_url,
            NormalizedItem.normalized_url != "",  # Skip empty URLs
            NormalizedItem.id < item.id,
            NormalizedItem.is_duplicate == False,  # noqa: E712
        ).first()

        if url_duplicate:
            logger.info(
                f"Marking item {item.id} as duplicate of {url_duplicate.id} (URL match)"
            )
            item.is_duplicate = True
            item.duplicate_of_id = url_duplicate.id
            return True

        return False

    def get_duplicate_chain(self, item_id: int) -> list[int]:
        """Get full chain of duplicates for an item.

        Args:
            item_id: Starting normalized_item ID

        Returns:
            List of IDs in duplicate chain (oldest to newest)
        """
        with get_db() as db:
            item = db.query(NormalizedItem).filter(
                NormalizedItem.id == item_id
            ).first()

            if not item:
                return []

            # Find root (oldest non-duplicate)
            root = item
            while root.duplicate_of_id:
                root = db.query(NormalizedItem).filter(
                    NormalizedItem.id == root.duplicate_of_id
                ).first()
                if not root:
                    break

            if not root:
                return [item_id]

            # Collect all duplicates pointing to root
            chain = [root.id]
            duplicates = db.query(NormalizedItem).filter(
                NormalizedItem.duplicate_of_id == root.id,
                NormalizedItem.is_duplicate == True,  # noqa: E712
            ).order_by(NormalizedItem.id).all()

            chain.extend([dup.id for dup in duplicates])

            return chain
