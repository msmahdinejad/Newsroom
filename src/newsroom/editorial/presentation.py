"""Public Telegram presentation for grounded Persian editorial output.

The editorial schema retains internal evidence and confidence fields for audit,
but the reader-facing report deliberately exposes only a title, a concise
summary, and the original source links for each story.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from newsroom.editorial.report_profiles import resolve_report_profile
from newsroom.editorial.schema import EditorialOutput, StoryEditorialResult

_SEPARATOR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
_EN_TITLES = {
    "scheduled": "Programming & Developer Tools",
    "manual": "Programming & Developer Tools",
    "manual_new": "New Programming Stories",
    "manual_comprehensive": "Comprehensive Programming Report",
    "platform_telegram": "Programming from Telegram",
    "platform_x": "Programming from X",
    "platform_web": "Programming from Websites",
    "platform_github": "GitHub Projects & Releases",
    "platform_reddit": "Programming from Reddit",
}


def render_persian_report(
    output: EditorialOutput,
    report_mode: str,
    *,
    now: datetime | None = None,
) -> str:
    """Render an intentionally compact reader-facing Persian Telegram report."""
    profile = resolve_report_profile(report_mode)
    language = output.metadata.report_language or "fa"
    rendered_at = now or datetime.now(UTC)
    high = [story for story in output.stories if story.suggested_priority == "high"]
    other = [story for story in output.stories if story.suggested_priority != "high"]
    if not high and other:
        promoted_count = min(5, max(1, len(other) // 5))
        high = other[:promoted_count]
        other = other[promoted_count:]

    title = _EN_TITLES.get(report_mode, "Programming News") if language == "en" else profile.title_fa
    important_label = "🔥 Top stories" if language == "en" else "🔥 \u062e\u0628\u0631\u0647\u0627\u06cc \u0645\u0647\u0645"
    other_label = "📰 More stories" if language == "en" else "📰 \u062e\u0628\u0631\u0647\u0627\u06cc \u062f\u06cc\u06af\u0631"
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


def _render_story(story: StoryEditorialResult) -> str:
    """Keep one story and its links together for Telegram semantic chunking."""
    lines = [f"🔹 {_compact(story.headline_fa)}", _compact(story.summary_fa)]
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
