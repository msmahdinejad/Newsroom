"""Evidence packet builder for editorial generation.

Builds bounded structured evidence from stories — NOT raw source text.
The LLM only sees: story ID, source names, source types, canonical links,
timestamps, extracted facts, contradiction notes, confidence, excerpts.
"""

from typing import Any

from sqlalchemy.orm import Session

from newsroom.logging import get_logger
from newsroom.storage.models import Evidence, NormalizedItem, Story, StoryItem

logger = get_logger(__name__)


class EvidenceBuilder:
    """Build evidence packets from stories."""

    def build_for_story(self, db: Session, story: Story) -> int:
        """Build and persist evidence packet for a story. Returns evidence ID."""
        items = (
            db.query(NormalizedItem)
            .join(StoryItem, StoryItem.item_id == NormalizedItem.id)
            .filter(StoryItem.story_id == story.id)
            .all()
        )

        packet = self._build_packet(story, items)
        evidence = Evidence(story_id=story.id, packet=packet)
        db.add(evidence)
        db.flush()
        logger.debug(f"Built evidence {evidence.id} for story {story.id}")
        return evidence.id

    def build_for_stories(self, db: Session, story_ids: list[int]) -> dict[str, int]:
        """Build evidence for multiple stories."""
        stats = {"packets_built": 0}
        for sid in story_ids:
            story = db.query(Story).filter_by(id=sid).first()
            if story:
                self.build_for_story(db, story)
                stats["packets_built"] += 1
        return stats

    def _build_packet(self, story: Story, items: list[NormalizedItem]) -> dict[str, Any]:
        """Build a bounded evidence packet."""
        sources = []
        for item in items:
            source_name = ""
            if item.raw_item and item.raw_item.source:
                source_name = item.raw_item.source.name
            sources.append({
                "name": source_name,
                "type": item.raw_item.source.type if item.raw_item and item.raw_item.source else "unknown",
                "url": item.source_url,
                "canonical_url": item.canonical_url,
                "title": item.title[:200],
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "language": item.language,
                "excerpt": (item.description or "")[:300],
            })

        return {
            "story_id": story.id,
            "headline": story.headline,
            "keywords": story.cluster_keywords,
            "trust_status": story.trust_status,
            "confidence": story.confidence,
            "importance_score": story.importance_score,
            "source_count": story.source_count,
            "item_count": len(items),
            "sources": sources,
            "facts": self._extract_facts(items),
            "contradictions": [],
        }

    def _extract_facts(self, items: list[NormalizedItem]) -> list[str]:
        """Extract candidate facts from items (titles + first sentences)."""
        facts = []
        seen = set()
        for item in items:
            # Title is the primary fact candidate
            if item.title and item.title not in seen:
                facts.append(item.title[:200])
                seen.add(item.title)
            # First sentence of description as secondary
            if item.description:
                first = item.description.split(".")[0].strip()
                if first and first not in seen and len(first) > 20:
                    facts.append(first[:200])
                    seen.add(first)
        return facts[:10]  # bounded
