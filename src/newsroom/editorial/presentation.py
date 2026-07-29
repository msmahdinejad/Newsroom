"""Public Telegram presentation for grounded localized editorial output.

The editorial schema retains internal evidence and confidence fields for audit,
but the reader-facing report deliberately exposes only a title, a concise
summary, and the original source links for each story.
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from newsroom.config import settings
from newsroom.editorial.report_profiles import resolve_report_profile
from newsroom.editorial.schema import EditorialOutput, StoryEditorialResult

_SEPARATOR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def render_report(
    output: EditorialOutput,
    report_mode: str,
    *,
    now: datetime | None = None,
    digest_name: str | None = None,
    timezone: str | None = None,
) -> str:
    """Render an intentionally compact localized Telegram report."""
    profile = resolve_report_profile(report_mode)
    language = output.metadata.report_language or "fa"
    rendered_at = now or datetime.now(ZoneInfo(timezone or settings.timezone))
    high = [story for story in output.stories if story.suggested_priority == "high"]
    other = [story for story in output.stories if story.suggested_priority != "high"]
    if not high and other:
        promoted_count = min(5, max(1, len(other) // 5))
        high = other[:promoted_count]
        other = other[promoted_count:]

    title = digest_name or (profile.title_en if language == "en" else profile.title_fa)
    important_label = (
        "🔥 Top stories"
        if language == "en"
        else "🔥 \u062e\u0628\u0631\u0647\u0627\u06cc \u0645\u0647\u0645"
    )
    other_label = (
        "📰 More stories"
        if language == "en"
        else "📰 \u062e\u0628\u0631\u0647\u0627\u06cc \u062f\u06cc\u06af\u0631"
    )
    lines = [
        f"📰 {title}",
        f"📅 {rendered_at.strftime('%Y-%m-%d')}",
        _SEPARATOR,
    ]
    if high:
        lines.extend((important_label, _SEPARATOR))
        lines.extend(_render_story(story) for story in high)
    if other:
        if high:
            lines.append(_SEPARATOR)
        lines.extend((other_label, _SEPARATOR))
        lines.extend(_render_story(story) for story in other)
    return "\n\n".join(lines)


def render_persian_report(
    output: EditorialOutput,
    report_mode: str,
    *,
    now: datetime | None = None,
    digest_name: str | None = None,
    timezone: str | None = None,
) -> str:
    """Compatibility adapter for integrations using the pre-v4 name."""
    return render_report(
        output,
        report_mode,
        now=now,
        digest_name=digest_name,
        timezone=timezone,
    )


def _render_story(story: StoryEditorialResult) -> str:
    """Keep one story and its links together for Telegram semantic chunking."""
    lines = [f"🔹 {_compact(story.headline)}", _compact(story.summary)]
    links = _unique_links(story.source_links)
    lines.extend(f"🔗 {link}" for link in links[:3])
    return "\n".join(line for line in lines if line)


def _compact(value: str) -> str:
    compact = " ".join(value.split())
    # Small models occasionally emit a detached first letter before the same
    # Persian word ("\u0627\u0646\u062a \u0627\u0646\u062a\u0634\u0627\u0631", "\u062f \u062f\u0648\u0631\u0647"). It is never meaningful prose.
    return re.sub(
        r"(?<!\S)([\u0622-\u06cc]{1,3})\s+(?=\1[\u0622-\u06cc])",
        "",
        compact,
    )


def _unique_links(links: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for link in links:
        clean = link.strip()
        if clean and clean not in seen:
            seen.add(clean)
            unique.append(clean)
    return unique
