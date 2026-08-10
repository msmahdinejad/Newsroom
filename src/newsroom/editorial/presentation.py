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
_PERSIAN_MONTHS = (
    "\u0641\u0631\u0648\u0631\u062f\u06cc\u0646",
    "\u0627\u0631\u062f\u06cc\u0628\u0647\u0634\u062a",
    "\u062e\u0631\u062f\u0627\u062f",
    "\u062a\u06cc\u0631",
    "\u0645\u0631\u062f\u0627\u062f",
    "\u0634\u0647\u0631\u06cc\u0648\u0631",
    "\u0645\u0647\u0631",
    "\u0622\u0628\u0627\u0646",
    "\u0622\u0630\u0631",
    "\u062f\u06cc",
    "\u0628\u0647\u0645\u0646",
    "\u0627\u0633\u0641\u0646\u062f",
)
_PERSIAN_DIGITS = str.maketrans("0123456789", "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9")


def render_report(
    output: EditorialOutput,
    report_mode: str,
    *,
    now: datetime | None = None,
    digest_name: str | None = None,
    timezone: str | None = None,
    delivery_config: dict[str, object] | None = None,
) -> str:
    """Render an intentionally compact localized Telegram report."""
    profile = resolve_report_profile(report_mode)
    language = output.metadata.report_language or "fa"
    rendered_at = now or datetime.now(ZoneInfo(timezone or settings.timezone))
    config = delivery_config or {}
    style = str(config.get("presentation_style", "sectioned"))
    date_style = str(config.get("date_style", "iso"))
    max_links = max(0, min(3, int(str(config.get("max_links_per_story", 3)))))
    footer = " ".join(str(config.get("footer_text", "")).split())
    high = [story for story in output.stories if story.suggested_priority == "high"]
    other = [story for story in output.stories if story.suggested_priority != "high"]
    if not high and other:
        promoted_count = min(5, max(1, len(other) // 5))
        high = other[:promoted_count]
        other = other[promoted_count:]

    title = digest_name or (profile.title_en if language == "en" else profile.title_fa)
    if style == "numbered":
        return _render_numbered_report(
            output.stories,
            title=title,
            language=language,
            rendered_at=rendered_at,
            date_style=date_style,
            max_links=max_links,
            footer=footer,
        )
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
        lines.extend(_render_story(story, max_links=max_links) for story in high)
    if other:
        if high:
            lines.append(_SEPARATOR)
        lines.extend((other_label, _SEPARATOR))
        lines.extend(_render_story(story, max_links=max_links) for story in other)
    if footer:
        lines.extend((_SEPARATOR, footer))
    return "\n\n".join(lines)


def render_persian_report(
    output: EditorialOutput,
    report_mode: str,
    *,
    now: datetime | None = None,
    digest_name: str | None = None,
    timezone: str | None = None,
    delivery_config: dict[str, object] | None = None,
) -> str:
    """Compatibility adapter for integrations using the pre-v4 name."""
    return render_report(
        output,
        report_mode,
        now=now,
        digest_name=digest_name,
        timezone=timezone,
        delivery_config=delivery_config,
    )


def _render_story(story: StoryEditorialResult, *, max_links: int = 3) -> str:
    """Keep one story and its links together for Telegram semantic chunking."""
    lines = [f"🔹 {_compact(story.headline)}", _compact(story.summary)]
    links = _unique_links(story.source_links)
    lines.extend(f"🔗 {link}" for link in links[:max_links])
    return "\n".join(line for line in lines if line)


def _render_numbered_report(
    stories: list[StoryEditorialResult],
    *,
    title: str,
    language: str,
    rendered_at: datetime,
    date_style: str,
    max_links: int,
    footer: str,
) -> str:
    ordered = sorted(
        enumerate(stories),
        key=lambda pair: (
            {"high": 0, "medium": 1, "low": 2}.get(pair[1].suggested_priority, 1),
            pair[0],
        ),
    )
    blocks = [
        f"🤖 {title}",
        f"📅 {format_report_date(rendered_at, language=language, style=date_style)}",
    ]
    for index, (_, story) in enumerate(ordered, start=1):
        number = str(index).translate(_PERSIAN_DIGITS) if language == "fa" else str(index)
        lines = [f"{number}. {_compact(story.headline)}", _compact(story.summary)]
        links = _unique_links(story.source_links)
        lines.extend(f"🔗 {link}" for link in links[:max_links])
        blocks.append("\n".join(line for line in lines if line))
    if footer:
        blocks.append(footer)
    return "\n\n".join(blocks)


def format_report_date(value: datetime, *, language: str, style: str) -> str:
    if style != "jalali":
        return value.strftime("%Y-%m-%d")
    year, month, day = _gregorian_to_jalali(value.year, value.month, value.day)
    if language == "fa":
        return f"{day} {_PERSIAN_MONTHS[month - 1]} {year}".translate(_PERSIAN_DIGITS)
    return f"{year:04d}-{month:02d}-{day:02d}"


def _gregorian_to_jalali(year: int, month: int, day: int) -> tuple[int, int, int]:
    """Convert a Gregorian date to Solar Hijri without a runtime dependency."""
    gregorian_month_days = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    year -= 1600
    month -= 1
    day -= 1
    day_number = 365 * year + (year + 3) // 4 - (year + 99) // 100 + (year + 399) // 400
    day_number += sum(gregorian_month_days[:month])
    if month > 1 and ((year + 1600) % 4 == 0 and ((year + 1600) % 100 != 0 or (year + 1600) % 400 == 0)):
        day_number += 1
    day_number += day

    jalali_day_number = day_number - 79
    cycles, jalali_day_number = divmod(jalali_day_number, 12_053)
    jalali_year = 979 + 33 * cycles + 4 * (jalali_day_number // 1_461)
    jalali_day_number %= 1_461
    if jalali_day_number >= 366:
        jalali_year += (jalali_day_number - 1) // 365
        jalali_day_number = (jalali_day_number - 1) % 365
    if jalali_day_number < 186:
        jalali_month = 1 + jalali_day_number // 31
        jalali_day = 1 + jalali_day_number % 31
    else:
        jalali_month = 7 + (jalali_day_number - 186) // 30
        jalali_day = 1 + (jalali_day_number - 186) % 30
    return jalali_year, jalali_month, jalali_day


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
