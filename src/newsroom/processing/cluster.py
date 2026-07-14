"""Story clustering - group related normalized items."""

from collections import Counter

from newsroom.config import settings
from newsroom.logging import get_logger
from newsroom.storage.database import get_db
from newsroom.storage.models import NormalizedItem, Story

logger = get_logger(__name__)


class Clusterer:
    """Cluster normalized items into stories by similarity."""

    def cluster_items(self, item_ids: list[int]) -> dict[str, int]:
        """Group items into stories based on keyword similarity.

        Args:
            item_ids: List of normalized_item IDs to cluster

        Returns:
            Stats dict: {stories_created, items_clustered}
        """
        stats = {
            "stories_created": 0,
            "items_clustered": 0,
        }

        with get_db() as db:
            # Get non-duplicate items only
            items = db.query(NormalizedItem).filter(
                NormalizedItem.id.in_(item_ids),
                NormalizedItem.is_duplicate == False,  # noqa: E712
            ).all()

            # Extract keywords for each item
            item_keywords = {}
            for item in items:
                keywords = self._extract_keywords(item.title + " " + (item.description or ""))
                item_keywords[item.id] = keywords

            # Build similarity graph
            clusters = []
            assigned = set()

            for item in items:
                if item.id in assigned:
                    continue

                # Start new cluster
                cluster = [item.id]
                assigned.add(item.id)

                # Find similar items
                for other in items:
                    if other.id == item.id or other.id in assigned:
                        continue

                    similarity = self._compute_similarity(
                        item_keywords[item.id],
                        item_keywords[other.id]
                    )

                    if similarity >= settings.cluster_keyword_threshold:
                        cluster.append(other.id)
                        assigned.add(other.id)

                clusters.append(cluster)

            # Create story for each cluster
            for cluster in clusters:
                story_items = [item for item in items if item.id in cluster]
                story = self._create_story(db, story_items)
                db.add(story)
                stats["stories_created"] += 1
                stats["items_clustered"] += len(cluster)

            db.commit()

        return stats

    def _extract_keywords(self, text: str) -> set[str]:
        """Extract significant keywords from text.

        Args:
            text: Input text

        Returns:
            Set of lowercase keywords
        """
        # ponytail: simple word extraction, no NLP library
        words = text.lower().split()

        # Filter stopwords and short words
        stopwords = {
            "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
            "been", "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "can", "this",
            "that", "these", "those", "i", "you", "he", "she", "it", "we", "they",
        }

        keywords = {
            word.strip(".,!?;:()[]{}\"'")
            for word in words
            if len(word) > 3 and word not in stopwords
        }

        # ponytail: preserve version numbers as compound keywords
        # "python 3.13" -> adds "python-3.13" to help cluster related releases
        for i, word in enumerate(words[:-1]):
            cleaned = word.strip(".,!?;:()[]{}\"'")
            next_cleaned = words[i + 1].strip(".,!?;:()[]{}\"'")

            if cleaned not in stopwords and len(cleaned) > 2 and next_cleaned and next_cleaned[0].isdigit():
                    compound = f"{cleaned}-{next_cleaned}"
                    keywords.add(compound)

        return keywords

    def _compute_similarity(self, keywords1: set[str], keywords2: set[str]) -> float:
        """Compute weighted Jaccard similarity between keyword sets.

        Compound keywords (containing version numbers like python-3.13) get
        double weight because they represent strong topical signals.

        Args:
            keywords1: First keyword set
            keywords2: Second keyword set

        Returns:
            Similarity score [0.0, 1.0]
        """
        if not keywords1 or not keywords2:
            return 0.0

        def weight(kw: str) -> float:
            """Higher weight for version compounds."""
            return 2.0 if "-" in kw and any(c.isdigit() for c in kw) else 1.0

        intersection = keywords1 & keywords2
        union = keywords1 | keywords2

        # Weighted Jaccard
        inter_weight = sum(weight(kw) for kw in intersection)
        union_weight = sum(weight(kw) for kw in union)

        return inter_weight / union_weight if union_weight > 0 else 0.0

    def _create_story(self, db, items: list[NormalizedItem]) -> Story:
        """Create story from clustered items.

        Args:
            db: Database session
            items: List of normalized items in cluster

        Returns:
            Story instance
        """
        # Use most common words from titles as headline
        all_words = []
        for item in items:
            all_words.extend(self._extract_keywords(item.title))

        word_counts = Counter(all_words)
        top_words = [word for word, count in word_counts.most_common(5)]
        headline = " ".join(top_words).title()

        # Collect source URLs and item IDs
        source_urls = [item.source_url for item in items]
        item_ids = [item.id for item in items]

        # Determine priority (highest from items)
        # ponytail: items don't have priority field yet, use default
        priority = "medium" if items else "low"

        return Story(
            headline=headline,
            source_urls=str(source_urls),  # JSON stored as string
            item_ids=str(item_ids),
            priority=priority,
        )
