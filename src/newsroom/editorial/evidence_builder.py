"""Build EditorialEvidenceSet from persisted stories and evidence packets.

Converts DB evidence records into bounded structured packets with stable
reference IDs for the editorial provider. No secrets, session data, or
unrelated items are included.
"""

from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from newsroom.config import settings
from newsroom.editorial.schema import (
    EVIDENCE_SCHEMA_VERSION,
    SYSTEM_PROMPT_VERSION,
    EditorialEvidenceSet,
    EvidenceSourceItem,
    EvidenceStoryPacket,
)
from newsroom.logging import get_logger
from newsroom.storage.models import Evidence, NormalizedItem, Story, StoryItem, TelegramChannel

logger = get_logger(__name__)


def build_evidence_set(
    db: Session,
    story_ids: list[int],
    report_mode: str = "scheduled",
    *,
    max_stories: int | None = None,
) -> EditorialEvidenceSet:
    """Build a bounded evidence set from persisted stories.

    Respects editorial cost controls: max stories per call, max evidence
    per story, max excerpt length.
    """
    max_stories = max_stories or settings.editorial_max_stories_per_call
    max_evidence = settings.editorial_max_evidence_per_story
    max_excerpt = settings.editorial_max_excerpt_length

    # Deterministic ordering by importance_score desc, then created_at desc
    stories = (
        db.query(Story)
        .filter(Story.id.in_(story_ids))
        .order_by(Story.importance_score.desc(), Story.created_at.desc())
        .limit(max_stories)
        .all()
    )

    story_packets: list[EvidenceStoryPacket] = []

    for story in stories:
        # Get normalized items for this story
        items = (
            db.query(NormalizedItem)
            .join(StoryItem, StoryItem.item_id == NormalizedItem.id)
            .filter(StoryItem.story_id == story.id)
            .order_by(NormalizedItem.published_at.desc())
            .limit(max_evidence)
            .all()
        )

        sources: list[EvidenceSourceItem] = []
        for seq, item in enumerate(items):
            ref_id = f"ev-{story.id}-{seq}"
            source_name = ""
            source_type = "unknown"
            source_trust = "unverified"
            source_trust_score = 0.0
            telegram_permalink = None
            repo_name = None
            release_version = None

            if item.raw_item and item.raw_item.source:
                src = item.raw_item.source
                source_name = src.name
                source_type = src.type

                # Get trust info from TelegramChannel if applicable
                if source_type == "telegram":
                    tc = db.query(TelegramChannel).filter_by(source_id=src.id).first()
                    if tc:
                        source_trust = tc.trust_class
                        source_trust_score = tc.trust_score
                        if tc.public_url:
                            telegram_permalink = tc.public_url

                # Detect GitHub repo name and version from title/raw data
                if source_type == "github_releases":
                    raw = item.raw_item.raw_data if item.raw_item else {}
                    repo_name = raw.get("name", "").split(" ")[0] if raw.get("name") else None
                    release_version = raw.get("tag_name")

            sources.append(
                EvidenceSourceItem(
                    ref_id=ref_id,
                    item_id=item.id,
                    source_name=source_name,
                    source_type=source_type,
                    source_trust=source_trust,
                    source_trust_score=source_trust_score,
                    published_at=item.published_at.isoformat() if item.published_at else None,
                    original_title=item.title[:200],
                    excerpt=(item.description or "")[:max_excerpt],
                    original_url=item.source_url,
                    telegram_permalink=telegram_permalink,
                    repo_name=repo_name,
                    release_version=release_version,
                    detected_language=item.language or "en",
                )
            )

        # Get latest evidence packet for facts/contradictions
        ev = db.query(Evidence).filter_by(story_id=story.id).order_by(Evidence.id.desc()).first()
        facts = ev.packet.get("facts", []) if ev and ev.packet else []
        contradictions = ev.packet.get("contradictions", []) if ev and ev.packet else []

        # Evidence freshness — most recent published_at
        pub_dates = [item.published_at for item in items if item.published_at]
        evidence_freshness = max(pub_dates).isoformat() if pub_dates else ""

        story_packets.append(
            EvidenceStoryPacket(
                story_id=story.id,
                headline=story.headline,
                keywords=story.cluster_keywords or [],
                trust_status=story.trust_status,
                confidence=story.confidence,
                importance_score=story.importance_score,
                source_count=story.source_count,
                item_count=len(items),
                sources=sources,
                facts=facts[:10],
                contradictions=contradictions,
                evidence_freshness=evidence_freshness,
                duplicate_cluster_info=None,
            )
        )

    return EditorialEvidenceSet(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        prompt_version=SYSTEM_PROMPT_VERSION,
        report_mode=report_mode,
        stories=story_packets,
    )


def evidence_set_hash(story_ids: list[int], report_mode: str) -> str:
    """Deterministic hash of the evidence selection (for caching without DB read)."""
    key = f"{report_mode}:{','.join(str(s) for s in sorted(story_ids))}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
