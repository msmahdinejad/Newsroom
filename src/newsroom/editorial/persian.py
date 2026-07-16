"""Persian editorial report generator — deterministic fallback.

Three layers: A (important briefing), B (topic sections), C (ریزخبرها).
Evidence-constrained: only uses data from evidence packets, not raw source text.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from newsroom.logging import get_logger
from newsroom.storage.models import Evidence, Report, Story

logger = get_logger(__name__)

# Persian category labels
CATEGORY_MAP = {
    "github_releases": "گیت‌هاب و پروژه‌های متن‌باز",
    "rss": "اخبار فناوری",
    "telegram": "تلگرام",
    "youtube": "ویدیوها و محتوای آموزشی",
}

TRUST_FA = {
    "official": "رسمی",
    "confirmed": "تأییدشده",
    "likely": "محتمل",
    "unconfirmed": "تأییدنشده",
    "rumor": "شایعه",
    "promotional": "تبلیغاتی",
    "suspicious": "مشکوک",
}

PRIORITY_FA = {
    "high": "مهم",
    "medium": "متوسط",
    "low": "کم",
}


class PersianEditorial:
    """Generate Persian reports from evidence packets."""

    def generate_report(
        self,
        db: Session,
        story_ids: list[int],
        report_mode: str = "scheduled",
    ) -> int:
        """Generate and persist a Persian report. Returns report ID."""
        stories = (
            db.query(Story)
            .filter(Story.id.in_(story_ids))
            .order_by(Story.importance_score.desc(), Story.created_at.desc())
            .all()
        )

        if not stories:
            content = self._empty_report(report_mode)
        else:
            # Fetch evidence packets
            evidence_map: dict[int, dict | None] = {}
            for story in stories:
                ev = db.query(Evidence).filter_by(story_id=story.id).order_by(Evidence.id.desc()).first()
                evidence_map[story.id] = ev.packet if ev else None

            content = self._render(stories, evidence_map, report_mode)

        report = Report(
            content_fa=content,
            story_ids=story_ids,
            report_mode=report_mode,
            generation_method="deterministic",
        )
        db.add(report)
        db.flush()
        logger.info(f"Created report {report.id} with {len(story_ids)} stories")
        return report.id

    def _render(
        self,
        stories: list[Story],
        evidence_map: dict[int, dict | None],
        report_mode: str,
    ) -> str:
        """Render the 3-layer Persian report."""
        now = datetime.now(UTC)
        header = self._format_header(now, report_mode)

        # Layer A: Important briefing (top 3 by importance)
        top = sorted(stories, key=lambda s: s.importance_score, reverse=True)[:3]
        layer_a = []
        if top:
            layer_a.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            layer_a.append("🔥 مهم‌ترین خبرها")
            layer_a.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for story in top:
                layer_a.append(self._format_major(story, evidence_map.get(story.id)))

        # Layer B: Topic sections (medium importance)
        medium = [s for s in stories if s not in top and s.importance_score >= 0.3]
        layer_b = []
        if medium:
            layer_b.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            layer_b.append("📋 اخبار مهم")
            layer_b.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for story in medium[:8]:
                layer_b.append(self._format_medium(story, evidence_map.get(story.id)))

        # Layer C: ریزخبرها
        low = [s for s in stories if s.importance_score < 0.3]
        layer_c = []
        if low:
            layer_c.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            layer_c.append("📰 ریزخبرها")
            layer_c.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for story in low[:15]:
                layer_c.append(self._format_brief(story, evidence_map.get(story.id)))

        footer = self._format_footer(len(stories), now)

        sections = [header] + layer_a + layer_b + layer_c + [footer]
        return "\n\n".join(sections)

    def _format_header(self, now: datetime, report_mode: str) -> str:
        mode_fa = {
            "scheduled": "زمان‌بندی‌شده",
            "manual": "فوری",
            "manual_new": "اخبار جدید",
            "manual_comprehensive": "جامع",
        }.get(report_mode, "")

        return f"""📰 گزارش خبری هوش مصنوعی و فناوری
تاریخ: {now.strftime("%Y-%m-%d")}
نوع گزارش: {mode_fa}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    def _format_major(self, story: Story, evidence: dict | None) -> str:
        """Layer A — full briefing with evidence."""
        lines = [f"🔹 {story.headline}"]

        trust = TRUST_FA.get(story.trust_status, story.trust_status)
        confidence_pct = int(story.confidence * 100)
        lines.append(f"وضعیت: {trust} | اطمینان: {confidence_pct}%")

        if evidence:
            # Use extracted facts
            facts = evidence.get("facts", [])
            if facts:
                lines.append(f"چه اتفاقی افتاد: {facts[0]}")
            if len(facts) > 1:
                lines.append(f"چرا مهم است: {facts[1]}")

            # Source links
            sources = evidence.get("sources", [])
            for src in sources[:3]:
                url = src.get("canonical_url") or src.get("url", "")
                if url:
                    lines.append(f"🔗 {url}")
            if len(sources) > 3:
                lines.append(f"... و {len(sources) - 3} منبع دیگر")

        return "\n".join(lines)

    def _format_medium(self, story: Story, evidence: dict | None) -> str:
        """Layer B — medium detail."""
        lines = [f"▸ {story.headline}"]
        trust = TRUST_FA.get(story.trust_status, story.trust_status)
        lines.append(f"  وضعیت: {trust}")

        if evidence:
            sources = evidence.get("sources", [])
            if sources:
                url = sources[0].get("canonical_url") or sources[0].get("url", "")
                if url:
                    lines.append(f"  🔗 {url}")

        return "\n".join(lines)

    def _format_brief(self, story: Story, evidence: dict | None) -> str:
        """Layer C — one-liner."""
        url = ""
        if evidence:
            sources = evidence.get("sources", [])
            if sources:
                url = sources[0].get("canonical_url") or sources[0].get("url", "")
        link = f" | 🔗 {url}" if url else ""
        return f"• {story.headline}{link}"

    def _format_footer(self, count: int, now: datetime) -> str:
        return f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 این گزارش شامل {count} خبر از منابع مختلف است
🤖 تولید شده توسط سیستم خبرخوان هوش مصنوعی
⏰ {now.strftime("%H:%M UTC")}"""

    def _empty_report(self, report_mode: str) -> str:
        now = datetime.now(UTC)
        return f"""📰 گزارش خبری هوش مصنوعی و فناوری
تاریخ: {now.strftime("%Y-%m-%d")}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

خبر جدیدی در این دوره یافت نشد.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
