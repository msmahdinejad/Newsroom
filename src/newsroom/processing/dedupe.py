"""Deduplication — exact (hash + URL) and near-duplicate (token similarity)."""

import hashlib

from sqlalchemy.orm import Session

from newsroom.logging import get_logger
from newsroom.storage.models import NormalizedItem

logger = get_logger(__name__)


class Deduplicator:
    """Detect and mark duplicate normalized items."""

    def deduplicate_batch(self, db: Session, item_ids: list[int]) -> dict[str, int]:
        """Mark duplicates in a batch. Uses provided session (no nested transactions)."""
        stats = {"duplicates_marked": 0, "exact_hash": 0, "url_match": 0, "near_dup": 0}

        items = db.query(NormalizedItem).filter(
            NormalizedItem.id.in_(item_ids),
            NormalizedItem.is_duplicate == False,  # noqa: E712
        ).all()

        for item in items:
            method = self._mark_if_duplicate(db, item)
            if method:
                stats["duplicates_marked"] += 1
                if method == "hash":
                    stats["exact_hash"] += 1
                elif method == "url":
                    stats["url_match"] += 1
                elif method == "near":
                    stats["near_dup"] += 1

        return stats

    def _mark_if_duplicate(self, db: Session, item: NormalizedItem) -> str | None:
        """Check and mark item as duplicate. Returns method name or None."""
        # Stage 1: Exact content hash
        hash_dup = db.query(NormalizedItem).filter(
            NormalizedItem.content_hash == item.content_hash,
            NormalizedItem.id < item.id,
            NormalizedItem.is_duplicate == False,  # noqa: E712
        ).first()
        if hash_dup:
            item.is_duplicate = True
            item.duplicate_of_id = hash_dup.id
            logger.debug(f"Hash dup: item {item.id} → {hash_dup.id}")
            return "hash"

        # Stage 2: URL hash
        if item.url_hash and item.url_hash != self._empty_hash():
            url_dup = db.query(NormalizedItem).filter(
                NormalizedItem.url_hash == item.url_hash,
                NormalizedItem.id < item.id,
                NormalizedItem.is_duplicate == False,  # noqa: E712
            ).first()
            if url_dup:
                item.is_duplicate = True
                item.duplicate_of_id = url_dup.id
                logger.debug(f"URL dup: item {item.id} → {url_dup.id}")
                return "url"

        # Stage 3: Near-duplicate via title token similarity
        near_dup = self._find_near_duplicate(db, item)
        if near_dup:
            item.is_duplicate = True
            item.duplicate_of_id = near_dup.id
            logger.debug(f"Near dup: item {item.id} → {near_dup.id}")
            return "near"

        return None

    def _find_near_duplicate(self, db: Session, item: NormalizedItem) -> NormalizedItem | None:
        """Token-based near-duplicate detection within time window."""
        from datetime import UTC, datetime, timedelta

        from newsroom.config import settings

        # Only check items within the time window
        cutoff = datetime.now(UTC) - timedelta(hours=settings.dedup_time_window_hours)
        candidates = db.query(NormalizedItem).filter(
            NormalizedItem.id < item.id,
            NormalizedItem.is_duplicate == False,  # noqa: E712
            NormalizedItem.processed_at >= cutoff,
        ).limit(500).all()

        item_tokens = self._tokenize(item.title)
        if not item_tokens:
            return None

        for candidate in candidates:
            sim = self._token_similarity(item_tokens, self._tokenize(candidate.title))
            if sim >= 0.7:  # 70% token overlap
                return candidate

        return None

    def _tokenize(self, text: str) -> set[str]:
        """Tokenize text for comparison."""
        import re
        return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 2}

    def _token_similarity(self, a: set[str], b: set[str]) -> float:
        """Jaccard similarity."""
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def _empty_hash(self) -> str:
        return hashlib.sha256(b"").hexdigest()
