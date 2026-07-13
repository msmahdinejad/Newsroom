"""Persian digest preview generator - deterministic templates."""

from datetime import datetime

from newsroom.logging import get_logger
from newsroom.storage.database import get_db
from newsroom.storage.models import Digest, Story

logger = get_logger(__name__)


class PreviewGenerator:
    """Generate deterministic Persian digest previews."""

    def generate_preview(self, story_ids: list[int]) -> str:
        """Generate Persian digest from stories.

        Args:
            story_ids: List of story IDs to include

        Returns:
            Persian digest text with source attribution
        """
        with get_db() as db:
            stories = db.query(Story).filter(Story.id.in_(story_ids)).all()

            if not stories:
                return self._empty_digest()

            # Group by priority
            high_priority = [s for s in stories if s.priority == "high"]
            medium_priority = [s for s in stories if s.priority == "medium"]
            low_priority = [s for s in stories if s.priority == "low"]

            sections = []

            # Header
            sections.append(self._format_header())

            # Main stories
            if high_priority:
                sections.append(self._format_section_header("مهم‌ترین خبرها"))
                for story in high_priority:
                    sections.append(self._format_story(story, detailed=True))

            # Medium priority
            if medium_priority:
                sections.append(self._format_section_header("اخبار مهم"))
                for story in medium_priority:
                    sections.append(self._format_story(story, detailed=True))

            # Compact low priority
            if low_priority:
                sections.append(self._format_section_header("ریزخبرها"))
                for story in low_priority:
                    sections.append(self._format_story(story, detailed=False))

            # Footer
            sections.append(self._format_footer(len(stories)))

            return "\n\n".join(sections)

    def create_digest(self, story_ids: list[int]) -> int:
        """Create and persist digest.

        Args:
            story_ids: List of story IDs

        Returns:
            Created digest ID
        """
        content = self.generate_preview(story_ids)

        with get_db() as db:
            digest = Digest(
                content_fa=content,
                story_ids=str(story_ids),
                delivered=False,
            )
            db.add(digest)
            db.commit()
            db.refresh(digest)

            logger.info(f"Created digest {digest.id} with {len(story_ids)} stories")
            return digest.id

    def _format_header(self) -> str:
        """Generate digest header."""
        now = datetime.now()
        persian_date = now.strftime("%Y-%m-%d")  # ponytail: ISO for now, jalali later

        return f"""گزارش خبری هوش مصنوعی و تکنولوژی
تاریخ: {persian_date}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    def _format_section_header(self, title: str) -> str:
        """Format section header."""
        return f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔥 {title}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    def _format_story(self, story: Story, detailed: bool = True) -> str:
        """Format a story entry.

        Args:
            story: Story instance
            detailed: If True, show full format; if False, compact

        Returns:
            Formatted story text
        """
        source_urls = eval(story.source_urls)  # noqa: S307

        if detailed:
            # Full format with headline and multiple sources
            lines = [f"📰 {story.headline}"]

            if len(source_urls) > 1:
                lines.append(f"منابع: {len(source_urls)} منبع")

            for i, url in enumerate(source_urls[:5], 1):  # Max 5 sources
                lines.append(f"🔗 {url}")

            if len(source_urls) > 5:
                lines.append(f"... و {len(source_urls) - 5} منبع دیگر")

            return "\n".join(lines)
        else:
            # Compact format - headline + one source
            primary_url = source_urls[0] if source_urls else ""
            return f"• {story.headline}\n  🔗 {primary_url}"

    def _format_footer(self, story_count: int) -> str:
        """Format digest footer."""
        return f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 این گزارش شامل {story_count} خبر از منابع مختلف است
🤖 تولید شده توسط سیستم خبرخوان هوش مصنوعی"""

    def _empty_digest(self) -> str:
        """Generate empty digest message."""
        now = datetime.now()
        persian_date = now.strftime("%Y-%m-%d")

        return f"""گزارش خبری هوش مصنوعی و تکنولوژی
تاریخ: {persian_date}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

خبر جدیدی در این دوره یافت نشد.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
