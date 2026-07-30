"""Closed registry of source platforms supported by Newsroom.

The registry is deliberately code-owned: users configure sources within these
platforms, but imported data cannot introduce executable adapter types.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourcePlatform:
    """Public platform and the collector source types that implement it."""

    key: str
    label: str
    source_types: frozenset[str]


PLATFORMS: tuple[SourcePlatform, ...] = (
    SourcePlatform("telegram", "Telegram", frozenset({"telegram"})),
    SourcePlatform("x", "X", frozenset({"x_timeline"})),
    SourcePlatform("reddit", "Reddit", frozenset({"reddit_subreddit"})),
    SourcePlatform("github", "GitHub", frozenset({"github_releases"})),
    SourcePlatform("web", "Websites", frozenset({"rss", "web_page"})),
)

PLATFORM_BY_KEY = {platform.key: platform for platform in PLATFORMS}
SOURCE_TYPE_TO_PLATFORM = {
    source_type: platform for platform in PLATFORMS for source_type in platform.source_types
}
USER_SOURCE_TYPES = frozenset(SOURCE_TYPE_TO_PLATFORM)

# Kept collectable for installations upgraded from older releases, but it is
# intentionally absent from USER_SOURCE_TYPES and cannot be imported anew.
LEGACY_SOURCE_TYPES = frozenset({"youtube_rss"})
COLLECTABLE_SOURCE_TYPES = USER_SOURCE_TYPES | LEGACY_SOURCE_TYPES


def expand_platforms(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Expand public platform names or concrete types into collector types."""
    if not values or values == ["all"]:
        return ()
    expanded: set[str] = set()
    for raw in values:
        value = raw.strip().lower()
        if value in PLATFORM_BY_KEY:
            expanded.update(PLATFORM_BY_KEY[value].source_types)
        elif value in USER_SOURCE_TYPES:
            expanded.add(value)
        else:
            choices = ", ".join(("all", *(item.key for item in PLATFORMS)))
            raise ValueError(f"source groups must use: {choices}")
    return tuple(sorted(expanded))


def normalize_user_source_type(value: str) -> str:
    """Return a supported concrete type or reject the imported row."""
    normalized = value.strip().lower()
    platform = PLATFORM_BY_KEY.get(normalized)
    if platform is not None and len(platform.source_types) == 1:
        return next(iter(platform.source_types))
    if normalized not in USER_SOURCE_TYPES:
        raise ValueError("unsupported source type")
    return normalized


def platform_label(source_type: str) -> str:
    """Return a stable display label without exposing adapter internals."""
    platform = SOURCE_TYPE_TO_PLATFORM.get(source_type)
    if platform is not None:
        return platform.label
    if source_type == "youtube_rss":
        return "YouTube (legacy)"
    raise ValueError("unsupported source type")
