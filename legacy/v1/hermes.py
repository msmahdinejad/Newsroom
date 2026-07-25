"""Archived legacy digest adapter; production uses the persistent router."""

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from newsroom.logging import get_logger
from newsroom.storage.database import engine
from newsroom.storage.models import Digest, Story

logger = get_logger(__name__)


class HermesEditorial:
    """Generate Persian digests using Hermes editorial skills."""

    def __init__(self):
        """Initialize editorial generator."""
        self.skill_name = "persian-tech-digest"

    def generate_digest(self, story_ids: list[int]) -> str:
        """Generate Persian digest from stories using Hermes.

        Args:
            story_ids: List of story IDs to include

        Returns:
            Persian digest text
        """
        session = Session(engine)
        try:
            # Fetch stories
            stories = session.query(Story).filter(Story.id.in_(story_ids)).all()

            if not stories:
                return self._empty_digest()

            # Build context for Hermes
            # Kept only for historical compatibility. Production commands use
            # newsroom.editorial and never invoke this adapter.
            return self._generate_preview(stories)

        finally:
            session.close()

    def _build_context(self, stories: list[Story]) -> dict[str, Any]:
        """Build context dict for Hermes editorial skill.

        Args:
            stories: List of Story objects

        Returns:
            Context dictionary with story data
        """
        context = {
            "stories": [],
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M"),
        }

        for story in stories:
            context["stories"].append({
                "headline": story.headline,
                "summary": story.summary,
                "source_urls": eval(story.source_urls),  # noqa: S307
                "priority": story.priority,
            })

        return context

    def _generate_preview(self, stories: list[Story]) -> str:
        """Generate a legacy deterministic preview.

        Args:
            stories: List of stories

        Returns:
            Persian preview text
        """
        lines = []
        lines.append("📰 گزارش فناوری و هوش مصنوعی")
        lines.append(f"{datetime.now().strftime('%Y/%m/%d - %H:%M')}")
        lines.append("")

        # Group by priority
        high = [s for s in stories if s.priority == "high"]
        medium = [s for s in stories if s.priority == "medium"]

        if high:
            lines.append("## مهم‌ترین خبرها")
            lines.append("")
            for story in high[:3]:
                lines.extend(self._format_story(story))

        if medium:
            lines.append("## اخبار دیگر")
            lines.append("")
            for story in medium[:5]:
                lines.extend(self._format_story(story, compact=True))

        lines.append("")
        lines.append(f"📊 {len(stories)} خبر از منابع مختلف")

        return "\n".join(lines)

    def _format_story(self, story: Story, compact: bool = False) -> list[str]:
        """Format single story as Persian text.

        Args:
            story: Story object
            compact: Use compact format

        Returns:
            List of formatted lines
        """
        lines = []
        lines.append(f"🔹 {story.headline}")

        if not compact and story.summary:
            lines.append(story.summary)

        # Add first source URL
        source_urls = eval(story.source_urls)  # noqa: S307
        if source_urls:
            lines.append(f"منبع: {source_urls[0]}")

        lines.append("")
        return lines

    def _empty_digest(self) -> str:
        """Return empty digest message.

        Returns:
            Persian empty message
        """
        return "خبر قابل توجهی در این دوره یافت نشد."


def create_digest(story_ids: list[int] | None = None) -> Digest:
    """Create and save digest.

    Args:
        story_ids: Optional list of story IDs, or fetch recent

    Returns:
        Created Digest object
    """
    session = Session(engine)
    try:
        if story_ids is None:
            # Fetch recent undigested stories
            result = session.execute(
                text("""
                    SELECT id FROM stories
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                    ORDER BY priority DESC, created_at DESC
                    LIMIT 20
                """)
            )
            story_ids = [row[0] for row in result]

        generator = HermesEditorial()
        content = generator.generate_digest(story_ids)

        digest = Digest(
            content_fa=content,
            story_ids=str(story_ids),
            delivered=False,
        )
        session.add(digest)
        session.commit()
        session.refresh(digest)

        logger.info(f"Created digest {digest.id} with {len(story_ids)} stories")
        return digest

    finally:
        session.close()
