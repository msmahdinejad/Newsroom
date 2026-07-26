"""Public Telegram presentation for grounded Persian editorial output.

The editorial schema retains internal evidence and confidence fields for audit,
but the reader-facing report deliberately exposes only a title, a concise
summary, and the original source links for each story.
"""

from __future__ import annotations

from datetime import UTC, datetime

from newsroom.editorial.schema import EditorialOutput, StoryEditorialResult

_SEPARATOR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def render_persian_report(
    output: EditorialOutput,
    report_mode: str,
    *,
    now: datetime | None = None,
) -> str:
    """Render an intentionally compact reader-facing Persian Telegram report."""
    del report_mode  # The delivery format is identical for scheduled and manual reports.
    rendered_at = now or datetime.now(UTC)
    high = [story for story in output.stories if story.suggested_priority == "high"]
    other = [story for story in output.stories if story.suggested_priority != "high"]

    lines = [
        "📰 اخبار فناوری",
        f"📅 {rendered_at.strftime('%Y-%m-%d')}",
        _SEPARATOR,
    ]
    if high:
        lines.extend(("🔥 خبرهای مهم", _SEPARATOR))
        lines.extend(_render_story(story) for story in high)
    if other:
        if high:
            lines.append(_SEPARATOR)
        lines.extend(("📰 خبرهای دیگر", _SEPARATOR))
        lines.extend(_render_story(story) for story in other)
    return "\n\n".join(lines)


def _render_story(story: StoryEditorialResult) -> str:
    """Keep one story and its links together for Telegram semantic chunking."""
    lines = [f"🔹 {_compact(story.headline_fa)}", _compact(story.summary_fa)]
    links = _unique_links(story.source_links)
    lines.extend(f"🔗 {link}" for link in links[:3])
    return "\n".join(line for line in lines if line)


def _compact(value: str) -> str:
    return " ".join(value.split())


def _unique_links(links: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for link in links:
        clean = link.strip()
        if clean and clean not in seen:
            seen.add(clean)
            unique.append(clean)
    return unique
