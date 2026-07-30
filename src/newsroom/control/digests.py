"""Named digest definitions and editorial interest policies.

This module is the configuration seam between the control plane, scheduler and
editorial pipeline. It owns validation and persistence while exposing immutable
snapshots to callers. No credential values are accepted or returned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from newsroom.sources.platforms import COLLECTABLE_SOURCE_TYPES, expand_platforms
from newsroom.storage.models import (
    DigestDefinition,
    DigestSource,
    NewsroomControlSettings,
    Source,
)

DEFAULT_DIGEST_SLUG = "default"
DEFAULT_DIGEST_NAME = "Default digest"
DEFAULT_TOPIC_BRIEF = (
    "Software development, programming tools, developer services, libraries, "
    "frameworks, APIs, open-source projects and engineering practices."
)
DEFAULT_SCHEDULE_TIMES = ("00:00", "06:00", "12:00", "18:00")
SUPPORTED_LANGUAGES = frozenset({"fa", "en"})


@dataclass(frozen=True)
class InterestPolicy:
    """User-defined subject boundaries used by selection and prompting."""

    topic_brief: str
    include_terms: tuple[str, ...] = ()
    exclude_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class DigestSnapshot:
    """Validated immutable view consumed by runtime modules."""

    id: int | None
    slug: str
    name: str
    interest: InterestPolicy
    output_language: str
    timezone: str
    source_types: tuple[str, ...]
    source_ids: tuple[int, ...]
    max_stories: int
    minimum_telegram_stories: int
    schedule_times: tuple[str, ...]
    schedule_enabled: bool
    enabled: bool
    provider_policy: dict[str, object]
    delivery_config: dict[str, object]


@dataclass(frozen=True)
class DigestUpdate:
    """Fields accepted by the digest configuration interface."""

    name: str | None = None
    topic_brief: str | None = None
    include_terms: tuple[str, ...] | None = None
    exclude_terms: tuple[str, ...] | None = None
    output_language: str | None = None
    timezone: str | None = None
    source_groups: tuple[str, ...] | None = None
    source_ids: tuple[int, ...] | None = None
    max_stories: int | None = None
    minimum_telegram_stories: int | None = None
    schedule_times: tuple[str, ...] | None = None
    schedule_enabled: bool | None = None
    enabled: bool | None = None
    provider_policy: dict[str, object] | None = None
    delivery_config: dict[str, object] | None = None


class DigestCatalog:
    """Persistence interface for named digest products."""

    def __init__(self, db: Session, *, default_timezone: str = "Asia/Tehran") -> None:
        self.db = db
        self.default_timezone = _normalize_timezone(default_timezone)

    def get(self, slug: str = DEFAULT_DIGEST_SLUG) -> DigestSnapshot:
        normalized_slug = _normalize_slug(slug)
        row = (
            self.db.query(DigestDefinition).filter(DigestDefinition.slug == normalized_slug).first()
        )
        if isinstance(row, DigestDefinition):
            return _snapshot(row)
        if normalized_slug == DEFAULT_DIGEST_SLUG:
            return self._legacy_default()
        raise LookupError("digest not found")

    def list(self, *, enabled: bool | None = None) -> tuple[DigestSnapshot, ...]:
        query = self.db.query(DigestDefinition)
        if enabled is not None:
            query = query.filter(DigestDefinition.enabled.is_(enabled))
        rows = query.order_by(DigestDefinition.name, DigestDefinition.id).all()
        if not rows and enabled is not False:
            return (self._legacy_default(),)
        return tuple(_snapshot(row) for row in rows)

    def create(
        self,
        *,
        slug: str,
        name: str,
        topic_brief: str,
        output_language: str = "fa",
        timezone: str | None = None,
    ) -> DigestSnapshot:
        normalized_slug = _normalize_slug(slug)
        existing = (
            self.db.query(DigestDefinition.id)
            .filter(DigestDefinition.slug == normalized_slug)
            .first()
        )
        if existing is not None:
            raise ValueError("digest slug already exists")
        row = DigestDefinition(
            slug=normalized_slug,
            name=_normalize_name(name),
            topic_brief=_normalize_topic(topic_brief),
            include_terms=[],
            exclude_terms=[],
            output_language=_normalize_language(output_language),
            timezone=_normalize_timezone(timezone or self.default_timezone),
            source_types=[],
            max_stories=15,
            minimum_telegram_stories=0,
            schedule_times=list(DEFAULT_SCHEDULE_TIMES),
            schedule_enabled=False,
            enabled=True,
            provider_policy={},
            delivery_config={},
        )
        self.db.add(row)
        self.db.flush()
        return _snapshot(row)

    def update(
        self,
        slug: str,
        change: DigestUpdate,
    ) -> DigestSnapshot:
        normalized_slug = _normalize_slug(slug)
        row = (
            self.db.query(DigestDefinition).filter(DigestDefinition.slug == normalized_slug).first()
        )
        if not isinstance(row, DigestDefinition):
            if normalized_slug != DEFAULT_DIGEST_SLUG:
                raise LookupError("digest not found")
            row = self._materialize_legacy_default()
        _apply_update(self.db, row, change, default_timezone=self.default_timezone)
        self.db.flush()
        if normalized_slug == DEFAULT_DIGEST_SLUG:
            self._write_legacy_projection(row)
        return _snapshot(row)

    def _legacy_default(self) -> DigestSnapshot:
        legacy = self.db.get(NewsroomControlSettings, 1)
        if not isinstance(legacy, NewsroomControlSettings):
            return DigestSnapshot(
                id=None,
                slug=DEFAULT_DIGEST_SLUG,
                name=DEFAULT_DIGEST_NAME,
                interest=InterestPolicy(DEFAULT_TOPIC_BRIEF),
                output_language="fa",
                timezone=self.default_timezone,
                source_types=(),
                source_ids=(),
                max_stories=15,
                minimum_telegram_stories=2,
                schedule_times=DEFAULT_SCHEDULE_TIMES,
                schedule_enabled=True,
                enabled=True,
                provider_policy={},
                delivery_config={},
            )
        return DigestSnapshot(
            id=None,
            slug=DEFAULT_DIGEST_SLUG,
            name=DEFAULT_DIGEST_NAME,
            interest=InterestPolicy(DEFAULT_TOPIC_BRIEF),
            output_language=_normalize_language(legacy.report_language),
            timezone=self.default_timezone,
            source_types=_safe_source_types(legacy.report_source_types),
            source_ids=(),
            max_stories=_normalize_story_count(legacy.report_story_count),
            minimum_telegram_stories=2,
            schedule_times=_safe_schedule_times(legacy.schedule_times),
            schedule_enabled=bool(legacy.schedule_enabled),
            enabled=True,
            provider_policy={},
            delivery_config={},
        )

    def _materialize_legacy_default(self) -> DigestDefinition:
        current = self._legacy_default()
        row = DigestDefinition(
            slug=current.slug,
            name=current.name,
            topic_brief=current.interest.topic_brief,
            include_terms=list(current.interest.include_terms),
            exclude_terms=list(current.interest.exclude_terms),
            output_language=current.output_language,
            timezone=current.timezone,
            source_types=list(current.source_types),
            max_stories=current.max_stories,
            minimum_telegram_stories=current.minimum_telegram_stories,
            schedule_times=list(current.schedule_times),
            schedule_enabled=current.schedule_enabled,
            enabled=current.enabled,
            provider_policy=current.provider_policy,
            delivery_config=current.delivery_config,
        )
        self.db.add(row)
        return row

    def _write_legacy_projection(self, row: DigestDefinition) -> None:
        legacy = self.db.get(NewsroomControlSettings, 1)
        if not isinstance(legacy, NewsroomControlSettings):
            legacy = NewsroomControlSettings(id=1)
            self.db.add(legacy)
        legacy.report_language = row.output_language
        legacy.report_source_types = list(row.source_types)
        legacy.report_story_count = row.max_stories
        legacy.schedule_times = list(row.schedule_times)
        legacy.schedule_enabled = row.schedule_enabled


def _snapshot(row: DigestDefinition) -> DigestSnapshot:
    source_ids = tuple(
        sorted(membership.source_id for membership in (row.sources or []) if membership.enabled)
    )
    return DigestSnapshot(
        id=row.id,
        slug=row.slug,
        name=row.name,
        interest=InterestPolicy(
            topic_brief=row.topic_brief,
            include_terms=tuple(row.include_terms or []),
            exclude_terms=tuple(row.exclude_terms or []),
        ),
        output_language=row.output_language,
        timezone=row.timezone,
        source_types=_safe_source_types(row.source_types),
        source_ids=source_ids,
        max_stories=_normalize_story_count(row.max_stories),
        minimum_telegram_stories=max(
            0,
            min(int(row.minimum_telegram_stories or 0), int(row.max_stories)),
        ),
        schedule_times=_safe_schedule_times(row.schedule_times),
        schedule_enabled=bool(row.schedule_enabled),
        enabled=bool(row.enabled),
        provider_policy=dict(row.provider_policy or {}),
        delivery_config=dict(row.delivery_config or {}),
    )


def _apply_update(
    db: Session,
    row: DigestDefinition,
    change: DigestUpdate,
    *,
    default_timezone: str,
) -> None:
    if change.name is not None:
        row.name = _normalize_name(change.name)
    if change.topic_brief is not None:
        row.topic_brief = _normalize_topic(change.topic_brief)
    if change.include_terms is not None:
        row.include_terms = list(_normalize_terms(change.include_terms))
    if change.exclude_terms is not None:
        row.exclude_terms = list(_normalize_terms(change.exclude_terms))
    if change.output_language is not None:
        row.output_language = _normalize_language(change.output_language)
    if change.timezone is not None:
        row.timezone = _normalize_timezone(change.timezone or default_timezone)
    if change.source_groups is not None:
        row.source_types = list(expand_platforms(list(change.source_groups)))
    if change.max_stories is not None:
        row.max_stories = _normalize_story_count(change.max_stories)
    if change.minimum_telegram_stories is not None:
        minimum = int(change.minimum_telegram_stories)
        if minimum < 0 or minimum > int(row.max_stories):
            raise ValueError("minimum Telegram stories must fit within max stories")
        row.minimum_telegram_stories = minimum
    if change.schedule_times is not None:
        times = normalize_schedule_times(change.schedule_times)
        row.schedule_times = list(times)
        row.schedule_enabled = bool(times)
    if change.schedule_enabled is not None:
        row.schedule_enabled = bool(change.schedule_enabled)
    if change.enabled is not None:
        row.enabled = bool(change.enabled)
    if change.provider_policy is not None:
        row.provider_policy = _safe_mapping(change.provider_policy, "provider policy")
    if change.delivery_config is not None:
        row.delivery_config = _safe_mapping(change.delivery_config, "delivery config")
    if change.source_ids is not None:
        _replace_source_memberships(db, row, change.source_ids)
    if int(row.minimum_telegram_stories or 0) > int(row.max_stories):
        raise ValueError("minimum Telegram stories must fit within max stories")


def _replace_source_memberships(
    db: Session,
    row: DigestDefinition,
    source_ids: tuple[int, ...],
) -> None:
    normalized = tuple(sorted({int(source_id) for source_id in source_ids}))
    if any(source_id <= 0 for source_id in normalized):
        raise ValueError("source ids must be positive integers")
    if normalized:
        found = {
            source.id
            for source in db.query(Source)
            .filter(
                Source.id.in_(normalized),
                Source.type.in_(COLLECTABLE_SOURCE_TYPES),
            )
            .all()
        }
        missing = set(normalized) - found
        if missing:
            raise ValueError("one or more sources do not exist or are unsupported")
    row.sources.clear()
    row.sources.extend(DigestSource(source_id=source_id, enabled=True) for source_id in normalized)


def normalize_schedule_times(times: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for value in times:
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value).strip())
        if match is None:
            raise ValueError("schedule times must use HH:MM")
        hour, minute = int(match.group(1)), int(match.group(2))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("schedule time is outside 00:00-23:59")
        normalized.add(f"{hour:02d}:{minute:02d}")
    if len(normalized) > 12:
        raise ValueError("at most 12 daily schedule times are allowed")
    return tuple(sorted(normalized))


def _normalize_slug(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", normalized):
        raise ValueError("digest slug must use lowercase letters, numbers and hyphens")
    return normalized


def _normalize_name(value: str) -> str:
    normalized = " ".join(value.split())
    if not 1 <= len(normalized) <= 200:
        raise ValueError("digest name must be between 1 and 200 characters")
    return normalized


def _normalize_topic(value: str) -> str:
    normalized = " ".join(value.split())
    if not 10 <= len(normalized) <= 2_000:
        raise ValueError("topic brief must be between 10 and 2000 characters")
    return normalized


def _normalize_terms(values: tuple[str, ...]) -> tuple[str, ...]:
    terms = tuple(
        dict.fromkeys(
            normalized for value in values if (normalized := " ".join(str(value).split()))
        )
    )
    if len(terms) > 100 or any(len(term) > 100 for term in terms):
        raise ValueError("interest terms exceed the supported limit")
    return terms


def _normalize_language(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in SUPPORTED_LANGUAGES:
        raise ValueError("language must be one of: fa, en")
    return normalized


def _normalize_timezone(value: str) -> str:
    normalized = value.strip()
    try:
        ZoneInfo(normalized)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return normalized


def _normalize_story_count(value: object) -> int:
    count = 15 if value is None else int(str(value))
    if not 1 <= count <= 50:
        raise ValueError("story count must be between 1 and 50")
    return count


def _safe_schedule_times(value: object) -> tuple[str, ...]:
    try:
        if not isinstance(value, (list, tuple)):
            raise ValueError
        return normalize_schedule_times(tuple(str(item) for item in value))
    except ValueError:
        return DEFAULT_SCHEDULE_TIMES


def _safe_source_types(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        source_type
        for source_type in value
        if isinstance(source_type, str) and source_type in COLLECTABLE_SOURCE_TYPES
    )


def _safe_mapping(value: dict[str, object], label: str) -> dict[str, object]:
    if any(
        marker in str(key).casefold()
        for key in value
        for marker in ("key", "secret", "token", "password", "credential")
    ):
        raise ValueError(f"{label} must not contain credential values")
    return dict(value)
