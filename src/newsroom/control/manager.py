"""Deep owner-control module.

Callers use one interface for validated runtime preferences, reversible source
administration, and bounded source-file imports. The implementation owns file
format details and database invariants; no credential material crosses this
seam.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy.orm import Session

from newsroom.storage.models import (
    NewsroomControlSettings,
    Source,
    SourceInventory,
)

DEFAULT_SCHEDULE_TIMES = ("00:00", "06:00", "12:00", "18:00")
SUPPORTED_LANGUAGES = frozenset({"fa", "en"})
SUPPORTED_SOURCE_TYPES = frozenset(
    {
        "telegram",
        "x_timeline",
        "rss",
        "web_page",
        "github_releases",
        "reddit_subreddit",
        "youtube_rss",
    }
)
SOURCE_GROUPS: dict[str, frozenset[str]] = {
    "telegram": frozenset({"telegram"}),
    "x": frozenset({"x_timeline"}),
    "web": frozenset({"rss", "web_page"}),
    "github": frozenset({"github_releases"}),
    "reddit": frozenset({"reddit_subreddit"}),
    "youtube": frozenset({"youtube_rss"}),
}
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 2_000

_HEADER_ALIASES = {
    "name": "name",
    "title": "name",
    "type": "type",
    "source_type": "type",
    "url": "url",
    "link": "url",
    "language": "language",
    "lang": "language",
    "category": "category",
    "topic": "category",
    "trust_class": "trust_class",
    "trust": "trust_class",
    "enabled": "enabled",
    "active": "enabled",
}


@dataclass(frozen=True)
class ControlSnapshot:
    report_language: str
    report_source_types: tuple[str, ...]
    report_story_count: int
    schedule_times: tuple[str, ...]
    schedule_enabled: bool


@dataclass(frozen=True)
class SourceActionResult:
    source_id: int
    action: str
    enabled: bool
    name: str


@dataclass(frozen=True)
class ImportResult:
    filename: str
    total_rows: int
    created: int
    updated: int
    skipped: int
    errors: tuple[str, ...]


class NewsroomControl:
    """Small interface over the complete owner-control implementation."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def settings(self) -> ControlSnapshot:
        row = self.db.get(NewsroomControlSettings, 1)
        if not isinstance(row, NewsroomControlSettings):
            return ControlSnapshot(
                report_language="fa",
                report_source_types=(),
                report_story_count=15,
                schedule_times=DEFAULT_SCHEDULE_TIMES,
                schedule_enabled=True,
            )
        return _snapshot(row)

    def configure(
        self,
        *,
        language: str | None = None,
        source_groups: str | list[str] | tuple[str, ...] | None = None,
        story_count: int | None = None,
        schedule_times: str | list[str] | tuple[str, ...] | None = None,
        schedule_enabled: bool | None = None,
    ) -> ControlSnapshot:
        row = self.db.get(NewsroomControlSettings, 1)
        if not isinstance(row, NewsroomControlSettings):
            row = NewsroomControlSettings(id=1)
            self.db.add(row)

        if language is not None:
            normalized_language = language.strip().lower()
            if normalized_language not in SUPPORTED_LANGUAGES:
                raise ValueError("language must be one of: fa, en")
            row.report_language = normalized_language

        if source_groups is not None:
            row.report_source_types = list(_expand_source_groups(source_groups))

        if story_count is not None:
            if not 1 <= int(story_count) <= 50:
                raise ValueError("story count must be between 1 and 50")
            row.report_story_count = int(story_count)

        if schedule_times is not None:
            normalized_times = _normalize_schedule_times(schedule_times)
            row.schedule_times = list(normalized_times)
            row.schedule_enabled = bool(normalized_times)

        if schedule_enabled is not None:
            row.schedule_enabled = bool(schedule_enabled)

        self.db.flush()
        return _snapshot(row)

    def list_sources(
        self,
        *,
        source_type: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Source], int]:
        page = max(1, page)
        page_size = max(1, min(50, page_size))
        query = self.db.query(Source)
        if source_type:
            normalized = _normalize_source_type(source_type)
            query = query.filter(Source.type == normalized)
        if enabled is not None:
            query = query.filter(Source.enabled.is_(enabled))
        total = query.count()
        rows = (
            query.order_by(Source.type, Source.name, Source.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total

    def set_source_enabled(self, source_id: int, enabled: bool) -> SourceActionResult:
        source = self.db.get(Source, int(source_id))
        if source is None:
            raise LookupError("source not found")
        source.enabled = enabled
        if enabled:
            source.inactive_reason = None
            if source.health_status == "unavailable":
                source.health_status = "configured"
        else:
            source.inactive_reason = "owner_disabled"
        self._sync_inventory(source, enabled, source.inactive_reason)
        self.db.flush()
        return SourceActionResult(
            source_id=source.id,
            action="enabled" if enabled else "disabled",
            enabled=source.enabled,
            name=source.name,
        )

    def delete_source(self, source_id: int, *, confirmed: bool = False) -> SourceActionResult:
        """Archive a source without deleting its cursor, items, or lineage."""
        if not confirmed:
            raise ValueError("source deletion requires explicit confirmation")
        source = self.db.get(Source, int(source_id))
        if source is None:
            raise LookupError("source not found")
        source.enabled = False
        source.inactive_reason = "owner_deleted"
        source.health_status = "unavailable"
        self._sync_inventory(source, False, "owner_deleted")
        self.db.flush()
        return SourceActionResult(
            source_id=source.id,
            action="deleted",
            enabled=False,
            name=source.name,
        )

    def import_sources(self, filename: str, content: bytes) -> ImportResult:
        safe_name = Path(filename).name
        if not safe_name:
            raise ValueError("source file name is required")
        if len(content) > MAX_IMPORT_BYTES:
            raise ValueError("source file exceeds the 5 MiB limit")
        suffix = Path(safe_name).suffix.lower()
        if suffix == ".csv":
            rows = _read_csv(content)
        elif suffix == ".xlsx":
            rows = _read_xlsx(content)
        else:
            raise ValueError("source file must be CSV or XLSX")
        if len(rows) > MAX_IMPORT_ROWS:
            raise ValueError("source file exceeds the 2000-row limit")

        created = 0
        updated = 0
        skipped = 0
        errors: list[str] = []
        for index, raw in enumerate(rows, start=2):
            try:
                normalized = _normalize_import_row(raw)
                identity = _stable_source_identity(
                    normalized["type"],
                    normalized["url"],
                )
                existing = (
                    self.db.query(Source)
                    .filter(Source.stable_identity == identity)
                    .first()
                )
                if existing is None:
                    existing = (
                        self.db.query(Source)
                        .filter(
                            Source.type == normalized["type"],
                            Source.url == normalized["url"],
                        )
                        .first()
                    )
                if existing is not None:
                    existing.url = normalized["url"]
                    existing.language = normalized["language"]
                    existing.category = normalized["category"]
                    existing.trust_class = normalized["trust_class"]
                    existing.stable_identity = existing.stable_identity or identity
                    if normalized["enabled"]:
                        existing.enabled = True
                        existing.inactive_reason = None
                    updated += 1
                    continue

                source = Source(
                    name=_unique_source_name(
                        self.db,
                        normalized["name"],
                    ),
                    type=normalized["type"],
                    url=normalized["url"],
                    language=normalized["language"],
                    category=normalized["category"],
                    trust_class=normalized["trust_class"],
                    # Imports are safe-by-default. The owner may opt in with an
                    # explicit enabled column or enable the row after review.
                    enabled=normalized["enabled"],
                    stable_identity=identity,
                    platform=_platform_for_type(normalized["type"]),
                    inactive_reason=None if normalized["enabled"] else "owner_review_required",
                    validation_status="untested",
                    health_status="configured",
                    no_cursor_reason="not_attempted",
                )
                self.db.add(source)
                created += 1
            except ValueError as exc:
                skipped += 1
                if len(errors) < 20:
                    errors.append(f"row {index}: {exc}")

        self.db.flush()
        return ImportResult(
            filename=safe_name,
            total_rows=len(rows),
            created=created,
            updated=updated,
            skipped=skipped,
            errors=tuple(errors),
        )

    def _sync_inventory(
        self,
        source: Source,
        enabled: bool,
        reason: str | None,
    ) -> None:
        rows = self.db.query(SourceInventory).filter_by(source_id=source.id).all()
        for row in rows:
            row.operational_state = "active" if enabled else "inactive"
            row.inactive_reason = None if enabled else reason


def _snapshot(row: NewsroomControlSettings) -> ControlSnapshot:
    language = str(row.report_language or "fa").lower()
    if language not in SUPPORTED_LANGUAGES:
        language = "fa"
    source_types = tuple(
        source_type
        for source_type in (row.report_source_types or [])
        if source_type in SUPPORTED_SOURCE_TYPES
    )
    try:
        times = _normalize_schedule_times(row.schedule_times or [])
    except ValueError:
        times = DEFAULT_SCHEDULE_TIMES
    return ControlSnapshot(
        report_language=language,
        report_source_types=source_types,
        report_story_count=max(1, min(50, int(row.report_story_count or 15))),
        schedule_times=times,
        schedule_enabled=bool(row.schedule_enabled),
    )


def _split_values(value: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(value, str):
        return [part for part in re.split(r"[,;\s]+", value) if part]
    return [str(part) for part in value]


def _expand_source_groups(
    groups: str | list[str] | tuple[str, ...],
) -> tuple[str, ...]:
    values = [value.strip().lower() for value in _split_values(groups)]
    if not values or values == ["all"]:
        return ()
    expanded: set[str] = set()
    for value in values:
        if value in SOURCE_GROUPS:
            expanded.update(SOURCE_GROUPS[value])
        elif value in SUPPORTED_SOURCE_TYPES:
            expanded.add(value)
        else:
            raise ValueError(
                "source groups must use: all, telegram, x, web, github, reddit, youtube"
            )
    return tuple(sorted(expanded))


def _normalize_schedule_times(
    times: str | list[str] | tuple[str, ...],
) -> tuple[str, ...]:
    values = _split_values(times)
    normalized: set[str] = set()
    for value in values:
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
        if match is None:
            raise ValueError("schedule times must use HH:MM")
        hour, minute = int(match.group(1)), int(match.group(2))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("schedule time is outside 00:00-23:59")
        normalized.add(f"{hour:02d}:{minute:02d}")
    if len(normalized) > 12:
        raise ValueError("at most 12 daily schedule times are allowed")
    return tuple(sorted(normalized))


def _normalize_source_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in SOURCE_GROUPS and len(SOURCE_GROUPS[normalized]) == 1:
        return next(iter(SOURCE_GROUPS[normalized]))
    if normalized not in SUPPORTED_SOURCE_TYPES:
        raise ValueError("unsupported source type")
    return normalized


def _read_csv(content: bytes) -> list[dict[str, Any]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8") from exc
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def _read_xlsx(content: bytes) -> list[dict[str, Any]]:
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(content),
            read_only=True,
            data_only=True,
        )
    except Exception as exc:
        raise ValueError("invalid XLSX file") from exc
    sheet = workbook.active
    rows = sheet.iter_rows(values_only=True)
    headers = next(rows, None)
    if headers is None:
        return []
    return [
        {
            str(headers[index] or ""): value
            for index, value in enumerate(row)
            if index < len(headers)
        }
        for row in rows
        if any(value not in (None, "") for value in row)
    ]


def _normalize_import_row(raw: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, str] = {}
    for header, value in raw.items():
        canonical = _HEADER_ALIASES.get(str(header).strip().lower())
        if canonical:
            mapped[canonical] = str(value or "").strip()
    name = mapped.get("name", "")
    source_type = _normalize_source_type(mapped.get("type", ""))
    url = _normalize_source_url(mapped.get("url", ""), source_type)
    if not name:
        raise ValueError("name is required")
    language = (mapped.get("language") or "en").lower()
    if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})?", language):
        raise ValueError("language must be a short language tag")
    return {
        "name": name[:255],
        "type": source_type,
        "url": url,
        "language": language[:10],
        "category": (mapped.get("category") or "programming")[:100],
        "trust_class": (mapped.get("trust_class") or "community")[:30],
        "enabled": (mapped.get("enabled") or "").lower() in {
            "1",
            "true",
            "yes",
            "on",
            "active",
        },
    }


def _normalize_source_url(value: str, source_type: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("url is required")
    if source_type == "reddit_subreddit" and raw.lower().startswith("r/"):
        raw = f"https://www.reddit.com/{raw}"
    elif source_type == "telegram" and raw.startswith("@"):
        raw = f"https://t.me/{raw[1:]}"
    elif source_type == "x_timeline" and raw.startswith("@"):
        raw = f"https://x.com/{raw[1:]}"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must use http or https")
    host = parsed.hostname.lower()
    path = parsed.path.rstrip("/")
    if source_type == "telegram" and host not in {"t.me", "www.t.me", "telegram.me"}:
        raise ValueError("Telegram sources must use a public t.me URL")
    if source_type == "github_releases":
        parts = [part for part in path.split("/") if part]
        if host not in {"github.com", "www.github.com"} or len(parts) < 2:
            raise ValueError("GitHub sources must use an owner/repository URL")
    return urlunparse(
        (
            "https",
            host,
            path,
            "",
            parsed.query if source_type == "rss" else "",
            "",
        )
    )


def _stable_source_identity(source_type: str, url: str) -> str:
    return hashlib.sha256(f"{source_type}:{url.casefold()}".encode()).hexdigest()


def _unique_source_name(db: Session, base: str) -> str:
    if db.query(Source).filter_by(name=base).first() is None:
        return base
    suffix = 2
    while db.query(Source).filter_by(name=f"{base} ({suffix})").first() is not None:
        suffix += 1
    return f"{base} ({suffix})"


def _platform_for_type(source_type: str) -> str:
    return {
        "telegram": "Telegram",
        "x_timeline": "X / Twitter",
        "github_releases": "GitHub",
        "reddit_subreddit": "Reddit",
        "youtube_rss": "YouTube / Social",
        "rss": "Website / Newsletter",
        "web_page": "Website / Newsletter",
    }[source_type]
