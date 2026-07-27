"""Repair legacy story clusters without touching raw or normalized source data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from newsroom.config import settings
from newsroom.processing.cluster import Clusterer
from newsroom.processing.normalize import Normalizer
from newsroom.storage.models import (
    Evidence,
    NormalizedItem,
    RawItem,
    Source,
    Story,
    StoryItem,
)


@dataclass(frozen=True)
class ClusterRepairStats:
    stories_examined: int = 0
    stories_split: int = 0
    stories_created: int = 0
    items_relinked: int = 0


def renormalize_reddit_items(db: Session) -> int:
    """Correct legacy Reddit rows from their untouched raw JSON."""
    rows = (
        db.query(NormalizedItem, RawItem)
        .join(RawItem, NormalizedItem.raw_item_id == RawItem.id)
        .join(Source, RawItem.source_id == Source.id)
        .filter(Source.type == "reddit_subreddit")
        .all()
    )
    normalizer = Normalizer()
    changed_item_ids: list[int] = []
    for item, raw_item in rows:
        values = normalizer.normalize(raw_item.raw_data)
        if (
            item.title == values["title"][:500]
            and (item.description or "") == values["description"][:2000]
        ):
            continue
        item.title = values["title"][:500]
        item.description = values["description"][:2000]
        item.source_url = values["source_url"]
        item.canonical_url = values["canonical_url"]
        item.published_at = values["published_at"]
        item.language = values["language"]
        item.content_hash = values["content_hash"]
        item.url_hash = values["url_hash"]
        changed_item_ids.append(item.id)

    if not changed_item_ids:
        return 0

    db.flush()
    affected_story_ids = [
        row[0]
        for row in (
            db.query(StoryItem.story_id)
            .filter(StoryItem.item_id.in_(changed_item_ids))
            .distinct()
            .all()
        )
    ]
    # Evidence was built from the malformed title/body and must be rebuilt.
    db.query(Evidence).filter(Evidence.story_id.in_(affected_story_ids)).delete(
        synchronize_session=False
    )
    refresh_story_metadata_for_items(db, changed_item_ids)
    return len(changed_item_ids)


def partition_story_items(
    items: list[NormalizedItem],
    clusterer: Clusterer | None = None,
) -> list[list[NormalizedItem]]:
    """Partition one legacy cluster using the corrected similarity contract."""
    engine = clusterer or Clusterer()
    keywords = {
        item.id: engine._extract_keywords(item.title)
        for item in items
    }
    partitions: list[list[NormalizedItem]] = []
    assigned: set[int] = set()
    for item in sorted(items, key=lambda candidate: candidate.id):
        if item.id in assigned:
            continue
        group = [item]
        assigned.add(item.id)
        for candidate in sorted(items, key=lambda value: value.id):
            if candidate.id in assigned:
                continue
            similarity = engine._compute_similarity(
                keywords[item.id],
                keywords[candidate.id],
            )
            if similarity >= settings.cluster_keyword_threshold:
                group.append(candidate)
                assigned.add(candidate.id)
        partitions.append(group)
    return partitions


def repair_polluted_story_clusters(
    db: Session,
    *,
    story_ids: list[int] | None = None,
) -> ClusterRepairStats:
    """Split incoherent multi-item stories transactionally.

    Source records, raw items, normalized items, historical reports, and
    deliveries remain untouched. The caller owns commit/rollback.
    """
    query = (
        db.query(StoryItem.story_id)
        .group_by(StoryItem.story_id)
        .having(func.count(StoryItem.item_id) > 1)
        .order_by(StoryItem.story_id)
    )
    if story_ids is not None:
        query = query.filter(StoryItem.story_id.in_(story_ids))
    candidate_ids = [row[0] for row in query.all()]

    engine = Clusterer()
    split_count = 0
    created_count = 0
    relinked_count = 0

    for story_id in candidate_ids:
        story = db.get(Story, story_id)
        if story is None:
            continue
        items = (
            db.query(NormalizedItem)
            .join(StoryItem, StoryItem.item_id == NormalizedItem.id)
            .filter(StoryItem.story_id == story_id)
            .order_by(NormalizedItem.id)
            .all()
        )
        partitions = partition_story_items(items, engine)
        if len(partitions) <= 1:
            continue

        split_count += 1
        original_created_at = story.created_at
        db.query(Evidence).filter(Evidence.story_id == story_id).delete(
            synchronize_session=False
        )
        db.query(StoryItem).filter(StoryItem.story_id == story_id).delete(
            synchronize_session=False
        )

        for index, partition in enumerate(partitions):
            generated = engine._create_story(db, partition)
            if index == 0:
                target = story
                target.headline = generated.headline
                target.summary = generated.summary
                target.priority = generated.priority
                target.trust_status = generated.trust_status
                target.confidence = generated.confidence
                target.importance_score = generated.importance_score
                target.novelty_score = generated.novelty_score
                target.cluster_keywords = generated.cluster_keywords
                target.source_count = generated.source_count
                target.material_version += 1
                target.material_change_at = datetime.now(UTC)
            else:
                target = generated
                target.created_at = original_created_at
                target.material_change_at = datetime.now(UTC)
                db.add(target)
                db.flush()
                created_count += 1

            for item in partition:
                db.add(StoryItem(story_id=target.id, item_id=item.id))
                relinked_count += 1

    db.flush()
    return ClusterRepairStats(
        stories_examined=len(candidate_ids),
        stories_split=split_count,
        stories_created=created_count,
        items_relinked=relinked_count,
    )


def refresh_story_metadata_for_items(
    db: Session,
    item_ids: list[int],
) -> int:
    """Refresh derived story headlines/scores after source normalization."""
    story_ids = [
        row[0]
        for row in (
            db.query(StoryItem.story_id)
            .filter(StoryItem.item_id.in_(item_ids))
            .distinct()
            .all()
        )
    ]
    engine = Clusterer()
    now = datetime.now(UTC)
    for story_id in story_ids:
        story = db.get(Story, story_id)
        if story is None:
            continue
        items = (
            db.query(NormalizedItem)
            .join(StoryItem, StoryItem.item_id == NormalizedItem.id)
            .filter(StoryItem.story_id == story_id)
            .all()
        )
        generated = engine._create_story(db, items)
        story.headline = generated.headline
        story.trust_status = generated.trust_status
        story.confidence = generated.confidence
        story.importance_score = generated.importance_score
        story.cluster_keywords = generated.cluster_keywords
        story.source_count = generated.source_count
        story.material_version += 1
        story.material_change_at = now
    db.flush()
    return len(story_ids)
