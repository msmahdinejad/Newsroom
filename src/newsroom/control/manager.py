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

from newsroom.control.digests import (
    DigestCatalog,
    DigestSnapshot,
    DigestUpdate,
)
from newsroom.sources.platforms import (
    COLLECTABLE_SOURCE_TYPES,
    expand_platforms,
    normalize_user_source_type,
    platform_label,
)
from newsroom.storage.models import (
    Source,
    SourceInventory,
)

SUPPORTED_SOURCE_TYPES = COLLECTABLE_SOURCE_TYPES
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
    digest_slug: str = "default"
    digest_name: str = "Default digest"
    topic_brief: str = ""
    include_terms: tuple[str, ...] = ()
    exclude_terms: tuple[str, ...] = ()
    timezone: str = "Asia/Tehran"
    source_ids: tuple[int, ...] = ()
    minimum_telegram_stories: int = 0
    provider_policy: dict[str, object] | None = None
    delivery_config: dict[str, object] | None = None


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
        self.digests = DigestCatalog(db)

    def settings(self) -> ControlSnapshot:
        return _control_snapshot(self.digests.get())

    def configure(
        self,
        *,
        language: str | None = None,
        source_groups: str | list[str] | tuple[str, ...] | None = None,
        story_count: int | None = None,
        schedule_times: str | list[str] | tuple[str, ...] | None = None,
        schedule_enabled: bool | None = None,
        name: str | None = None,
        topic_brief: str | None = None,
        include_terms: str | list[str] | tuple[str, ...] | None = None,
        exclude_terms: str | list[str] | tuple[str, ...] | None = None,
        timezone: str | None = None,
        source_ids: list[int] | tuple[int, ...] | None = None,
        minimum_telegram_stories: int | None = None,
    ) -> ControlSnapshot:
        source_values = tuple(_split_values(source_groups)) if source_groups is not None else None
        time_values = tuple(_split_values(schedule_times)) if schedule_times is not None else None
        included = tuple(_split_terms(include_terms)) if include_terms is not None else None
        excluded = tuple(_split_terms(exclude_terms)) if exclude_terms is not None else None
        updated = self.digests.update(
            "default",
            DigestUpdate(
                name=name,
                topic_brief=topic_brief,
                include_terms=included,
                exclude_terms=excluded,
                output_language=language,
                timezone=timezone,
                source_groups=source_values,
                source_ids=tuple(source_ids) if source_ids is not None else None,
                max_stories=story_count,
                minimum_telegram_stories=minimum_telegram_stories,
                schedule_times=time_values,
                schedule_enabled=schedule_enabled,
            ),
        )
        return _control_snapshot(updated)

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

    def add_source(
        self,
        *,
        name: str,
        source_type: str,
        url: str,
        language: str = "en",
        category: str = "general",
        trust_class: str = "community",
        enabled: bool = False,
    ) -> SourceActionResult:
        """Add one source within the closed platform registry."""
        normalized_type = _normalize_source_type(source_type)
        normalized_url = _normalize_source_url(url, normalized_type)
        identity = _stable_source_identity(normalized_type, normalized_url)
        normalized_name = " ".join(name.split())
        if not normalized_name:
            raise ValueError("name is required")
        existing = self.db.query(Source).filter(Source.stable_identity == identity).first()
        if isinstance(existing, Source):
            if enabled:
                existing.enabled = True
                existing.inactive_reason = None
            self.db.flush()
            return SourceActionResult(
                source_id=existing.id,
                action="existing",
                enabled=existing.enabled,
                name=existing.name,
            )
        normalized_language = language.strip().lower()
        if not re.fullmatch(
            r"[a-z]{2,3}(?:-[a-z0-9]{2,8})?",
            normalized_language,
        ):
            raise ValueError("language must be a short language tag")
        source = Source(
            name=_unique_source_name(self.db, normalized_name[:255]),
            type=normalized_type,
            url=normalized_url,
            language=normalized_language[:10],
            category=(" ".join(category.split()) or "general")[:100],
            trust_class=(" ".join(trust_class.split()) or "community")[:30],
            enabled=enabled,
            stable_identity=identity,
            platform=_platform_for_type(normalized_type),
            inactive_reason=None if enabled else "owner_review_required",
            validation_status="untested",
            health_status="configured",
            no_cursor_reason="not_attempted",
        )
        self.db.add(source)
        self.db.flush()
        return SourceActionResult(
            source_id=source.id,
            action="created",
            enabled=source.enabled,
            name=source.name,
        )

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
                existing = self.db.query(Source).filter(Source.stable_identity == identity).first()
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


def _control_snapshot(digest: DigestSnapshot) -> ControlSnapshot:
    return ControlSnapshot(
        report_language=digest.output_language,
        report_source_types=digest.source_types,
        report_story_count=digest.max_stories,
        schedule_times=digest.schedule_times,
        schedule_enabled=digest.schedule_enabled,
        digest_slug=digest.slug,
        digest_name=digest.name,
        topic_brief=digest.interest.topic_brief,
        include_terms=digest.interest.include_terms,
        exclude_terms=digest.interest.exclude_terms,
        timezone=digest.timezone,
        source_ids=digest.source_ids,
        minimum_telegram_stories=digest.minimum_telegram_stories,
        provider_policy=digest.provider_policy,
        delivery_config=digest.delivery_config,
    )


def _split_values(value: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(value, str):
        return [part for part in re.split(r"[,;\s]+", value) if part]
    return [str(part) for part in value]


def _split_terms(value: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,;]+", value) if part.strip()]
    return [str(part).strip() for part in value if str(part).strip()]


def _expand_source_groups(
    groups: str | list[str] | tuple[str, ...],
) -> tuple[str, ...]:
    return expand_platforms([value.strip().lower() for value in _split_values(groups)])


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
    return normalize_user_source_type(value)


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
        "category": (mapped.get("category") or "general")[:100],
        "trust_class": (mapped.get("trust_class") or "community")[:30],
        "enabled": (mapped.get("enabled") or "").lower()
        in {
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
    return platform_label(source_type)
