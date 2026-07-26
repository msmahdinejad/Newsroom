"""Continuous, bounded raw-to-story processing for production collectors.

Collectors persist raw records independently. This worker is the single seam
that promotes a bounded batch into normalized, deduplicated, clustered items
so newly ingested Telegram posts become eligible for editorial selection.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from newsroom.config import settings
from newsroom.logging import get_logger, setup_logging
from newsroom.processing.cluster import Clusterer
from newsroom.processing.dedupe import Deduplicator
from newsroom.processing.normalize import Normalizer
from newsroom.storage.database import get_db
from newsroom.storage.models import NormalizedItem, RawItem, Source

logger = get_logger(__name__)


@dataclass(frozen=True)
class ProcessingCycle:
    raw_seen: int
    normalized: int
    duplicates: int
    clustered: int


def process_pending_items(
    *,
    batch_size: int | None = None,
    source_type: str | None = None,
) -> ProcessingCycle:
    """Process one bounded batch, optionally prioritising one source platform."""
    limit = max(1, batch_size or settings.processing_batch_size)
    with get_db() as db:
        query = (
            db.query(RawItem)
            .join(Source, RawItem.source_id == Source.id)
            .outerjoin(NormalizedItem, RawItem.id == NormalizedItem.raw_item_id)
            .filter(NormalizedItem.id.is_(None))
        )
        if source_type:
            query = query.filter(Source.type == source_type)
        raw_items = (
            query.order_by(RawItem.collected_at.asc(), RawItem.id.asc())
            # Claim raw rows for this transaction.  A simultaneous pipeline
            # run sees only unlocked work instead of racing this insert.
            .with_for_update(of=RawItem, skip_locked=True)
            .limit(limit)
            .all()
        )
        if not raw_items:
            return ProcessingCycle(0, 0, 0, 0)

        normalizer = Normalizer()
        normalized_ids: list[int] = []
        for raw_item in raw_items:
            try:
                values = normalizer.normalize(raw_item.raw_data)
                normalized = NormalizedItem(
                    raw_item_id=raw_item.id,
                    title=values["title"][:500],
                    description=values.get("description", "")[:2000],
                    source_url=values["source_url"],
                    canonical_url=values.get("canonical_url", ""),
                    published_at=values.get("published_at"),
                    language=values.get("language"),
                    content_hash=values["content_hash"],
                    url_hash=values.get("url_hash", ""),
                )
                db.add(normalized)
                db.flush()
                normalized_ids.append(int(normalized.id))
            except Exception as exc:
                logger.error("Raw item normalization failed", extra={"raw_item_id": raw_item.id, "error_type": type(exc).__name__})

        if not normalized_ids:
            return ProcessingCycle(len(raw_items), 0, 0, 0)

        dedupe = Deduplicator().deduplicate_batch(db, normalized_ids)
        cluster = Clusterer().cluster_items(db, normalized_ids)
        return ProcessingCycle(
            raw_seen=len(raw_items),
            normalized=len(normalized_ids),
            duplicates=dedupe["duplicates_marked"],
            clustered=cluster["items_clustered"],
        )


class ProcessingWorker:
    """Repeat bounded processing cycles without coupling collectors to editorial work."""

    def __init__(
        self,
        *,
        run_cycle: Callable[[], int] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        interval_seconds: float | None = None,
    ) -> None:
        self._run_cycle = run_cycle or _run_production_cycle
        self._sleep = sleep
        self._interval_seconds = max(1.0, interval_seconds or settings.processing_loop_seconds)

    def run(self, *, max_cycles: int | None = None) -> None:
        completed = 0
        while max_cycles is None or completed < max_cycles:
            exit_code = self._run_cycle()
            completed += 1
            if exit_code:
                logger.warning("Processing cycle completed with an error", extra={"exit_code": exit_code})
            if max_cycles is None or completed < max_cycles:
                self._sleep(self._interval_seconds)


def _run_production_cycle() -> int:
    try:
        priority_source_type = settings.processing_priority_source_type.strip()
        result = process_pending_items(source_type=priority_source_type or None)
        # Keep every collector moving after the priority queue is caught up.
        if priority_source_type and not result.raw_seen:
            result = process_pending_items()
        logger.info(
            "Processing cycle complete",
            extra={
                "raw_seen": result.raw_seen,
                "normalized": result.normalized,
                "duplicates": result.duplicates,
                "clustered": result.clustered,
            },
        )
        return 0
    except Exception as exc:
        logger.exception("Processing cycle failed", extra={"error_type": type(exc).__name__})
        return 1


def main() -> None:
    setup_logging()
    ProcessingWorker().run()


if __name__ == "__main__":
    main()
