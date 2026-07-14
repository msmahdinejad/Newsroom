"""Story clustering — group related items by keyword similarity.

Uses weighted Jaccard with version-compound keywords. Also handles
cross-language clustering by normalizing Persian/English common terms.
"""

import re
from collections import Counter

from sqlalchemy.orm import Session

from newsroom.config import settings
from newsroom.logging import get_logger
from newsroom.storage.models import NormalizedItem, Story, StoryItem

logger = get_logger(__name__)

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "can", "this",
    "that", "these", "those", "i", "you", "he", "she", "it", "we", "they",
    # Persian stopwords
    "در", "از", "به", "که", "این", "را", "برای", "با", "است", "شد",
    "می", "آن", "یک", "تا", "بر", "یا", "هم", "نیز", "اما", "هر",
}


class Clusterer:
    """Cluster normalized items into stories."""

    def cluster_items(self, db: Session, item_ids: list[int]) -> dict[str, int]:
        """Group items into stories based on keyword similarity."""
        stats = {"stories_created": 0, "items_clustered": 0}

        items = db.query(NormalizedItem).filter(
            NormalizedItem.id.in_(item_ids),
            NormalizedItem.is_duplicate == False,  # noqa: E712
        ).all()

        # Check which items already have story links
        linked_ids = set()
        existing = db.query(StoryItem.item_id).filter(
            StoryItem.item_id.in_([i.id for i in items])
        ).all()
        linked_ids = {r[0] for r in existing}

        # Only cluster unlinked items
        new_items = [i for i in items if i.id not in linked_ids]
        if not new_items:
            return stats

        item_keywords: dict[int, set[str]] = {}
        for item in new_items:
            text = item.title + " " + (item.description or "")
            item_keywords[item.id] = self._extract_keywords(text)

        # Build clusters
        clusters: list[list[int]] = []
        assigned: set[int] = set()

        for item in new_items:
            if item.id in assigned:
                continue
            cluster = [item.id]
            assigned.add(item.id)

            for other in new_items:
                if other.id == item.id or other.id in assigned:
                    continue
                sim = self._compute_similarity(item_keywords[item.id], item_keywords[other.id])
                if sim >= settings.cluster_keyword_threshold:
                    cluster.append(other.id)
                    assigned.add(other.id)

            clusters.append(cluster)

        # Create stories
        for cluster_ids in clusters:
            cluster_items = [i for i in new_items if i.id in cluster_ids]
            story = self._create_story(db, cluster_items)
            db.add(story)
            db.flush()  # get story.id

            for ci in cluster_items:
                link = StoryItem(story_id=story.id, item_id=ci.id)
                db.add(link)

            stats["stories_created"] += 1
            stats["items_clustered"] += len(cluster_ids)

        return stats

    def _extract_keywords(self, text: str) -> set[str]:
        """Extract significant keywords with version compounds."""
        words = re.findall(r"[\w\u0600-\u06FF]+", text.lower())
        keywords = {w for w in words if len(w) > 2 and w not in _STOPWORDS}

        # Version compounds: "python 3.13" → "python-3.13"
        for i, w in enumerate(words[:-1]):
            nxt = words[i + 1]
            if w not in _STOPWORDS and len(w) > 2 and nxt and nxt[0].isdigit():
                keywords.add(f"{w}-{nxt}")

        return keywords

    def _compute_similarity(self, a: set[str], b: set[str]) -> float:
        """Weighted Jaccard — version compounds get double weight."""
        if not a or not b:
            return 0.0

        def weight(kw: str) -> float:
            return 2.0 if "-" in kw and any(c.isdigit() for c in kw) else 1.0

        inter = sum(weight(kw) for kw in (a & b))
        union = sum(weight(kw) for kw in (a | b))
        return inter / union if union > 0 else 0.0

    def _create_story(self, db: Session, items: list[NormalizedItem]) -> Story:
        """Create story from clustered items."""
        all_words: list[str] = []
        for item in items:
            all_words.extend(self._extract_keywords(item.title))

        word_counts = Counter(all_words)
        top_words = [w for w, _ in word_counts.most_common(5)]
        headline = " ".join(top_words).title() if top_words else items[0].title

        # Source count = distinct source_ids
        source_ids = set()
        for item in items:
            if item.raw_item and item.raw_item.source_id:
                source_ids.add(item.raw_item.source_id)

        # Score: more sources + more items = higher importance
        importance = min(len(items) * 0.3 + len(source_ids) * 0.2, 1.0)
        confidence = min(len(source_ids) * 0.3, 1.0)

        # Trust status based on source count
        if len(source_ids) >= 3:
            trust = "confirmed"
        elif len(source_ids) >= 2:
            trust = "likely"
        else:
            trust = "unconfirmed"

        return Story(
            headline=headline[:500],
            summary="",
            priority="medium",
            trust_status=trust,
            confidence=confidence,
            importance_score=importance,
            novelty_score=0.5,
            cluster_keywords=top_words,
            source_count=len(source_ids),
        )
