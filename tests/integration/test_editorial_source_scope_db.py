"""PostgreSQL coverage for digest-scoped editorial evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from newsroom.control.digests import InterestPolicy
from newsroom.editorial.evidence_builder import build_evidence_set
from newsroom.storage.models import Evidence, NormalizedItem, RawItem, Source, Story, StoryItem

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def cleanup_scope_data(db: Session):
    """Keep this integration module isolated from the shared test database."""
    yield
    db.rollback()
    source_ids = [
        row[0]
        for row in db.execute(text("SELECT id FROM sources WHERE name IN ('allowed', 'excluded')"))
    ]
    if source_ids:
        story_ids = [
            row[0]
            for row in db.execute(
                text(
                    "SELECT DISTINCT si.story_id FROM story_items si "
                    "JOIN normalized_items ni ON ni.id = si.item_id "
                    "JOIN raw_items ri ON ri.id = ni.raw_item_id "
                    "WHERE ri.source_id = ANY(:source_ids)"
                ),
                {"source_ids": source_ids},
            )
        ]
        if story_ids:
            db.execute(text("DELETE FROM evidence WHERE story_id = ANY(:ids)"), {"ids": story_ids})
            db.execute(
                text("DELETE FROM story_items WHERE story_id = ANY(:ids)"),
                {"ids": story_ids},
            )
            db.execute(text("DELETE FROM stories WHERE id = ANY(:ids)"), {"ids": story_ids})
        db.execute(
            text(
                "DELETE FROM normalized_items WHERE raw_item_id IN "
                "(SELECT id FROM raw_items WHERE source_id = ANY(:source_ids))"
            ),
            {"source_ids": source_ids},
        )
        db.execute(
            text("DELETE FROM raw_items WHERE source_id = ANY(:source_ids)"),
            {"source_ids": source_ids},
        )
        db.execute(
            text("DELETE FROM sources WHERE id = ANY(:source_ids)"), {"source_ids": source_ids}
        )
    db.commit()


def _add_item(
    db: Session,
    source: Source,
    *,
    title: str,
    url: str,
    published_at: datetime | None = None,
) -> NormalizedItem:
    raw = RawItem(source_id=source.id, raw_data={"title": title})
    db.add(raw)
    db.flush()
    item = NormalizedItem(
        raw_item_id=raw.id,
        title=title,
        description=f"Detailed editorial context for {title}",
        source_url=url,
        canonical_url=url,
        published_at=published_at or datetime.now(UTC),
        content_hash=("a" if source.name == "allowed" else "b") * 64,
    )
    db.add(item)
    db.flush()
    return item


def test_digest_scope_excludes_unselected_cluster_content(db: Session):
    allowed = Source(
        name="allowed",
        type="rss",
        url="https://allowed.example/feed",
        category="artificial intelligence",
        enabled=True,
    )
    excluded = Source(
        name="excluded",
        type="rss",
        url="https://excluded.example/feed",
        category="artificial intelligence",
        enabled=True,
    )
    db.add_all([allowed, excluded])
    db.flush()
    allowed_item = _add_item(
        db,
        allowed,
        title="Allowed AI model release",
        url="https://allowed.example/model",
    )
    excluded_item = _add_item(
        db,
        excluded,
        title="Excluded aggregator rumor",
        url="https://excluded.example/rumor",
    )
    stale_allowed_item = _add_item(
        db,
        allowed,
        title="Stale allowed archive item",
        url="https://allowed.example/archive",
        published_at=datetime.now(UTC) - timedelta(days=30),
    )
    story = Story(
        headline=excluded_item.title,
        importance_score=0.9,
        trust_status="likely",
        source_count=2,
    )
    db.add(story)
    db.flush()
    db.add_all(
        [
            StoryItem(story_id=story.id, item_id=allowed_item.id),
            StoryItem(story_id=story.id, item_id=excluded_item.id),
            StoryItem(story_id=story.id, item_id=stale_allowed_item.id),
            Evidence(
                story_id=story.id,
                packet={
                    "facts": ["Excluded aggregator rumor"],
                    "contradictions": [],
                },
            ),
        ]
    )
    db.flush()

    evidence = build_evidence_set(
        db,
        [story.id],
        source_ids=(allowed.id,),
        interest=InterestPolicy(
            topic_brief="artificial intelligence",
            include_terms=("AI",),
        ),
    )

    assert len(evidence.stories) == 1
    packet = evidence.stories[0]
    assert packet.headline == "Allowed AI model release"
    assert packet.source_count == 1
    assert [source.source_name for source in packet.sources] == ["allowed"]
    assert "Allowed AI model release" in packet.facts
    assert "Excluded aggregator rumor" not in packet.facts
    assert "Stale allowed archive item" not in packet.facts
