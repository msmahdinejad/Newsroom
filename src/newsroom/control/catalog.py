"""Credential-free source catalog initialization.

The module exposes one interface for the three supported first-run choices:
an empty registry, the packaged starter catalog, or an operator-supplied
CSV/XLSX file. Runtime source state remains in PostgreSQL; catalog files never
contain cookies, tokens, sessions, or request headers.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from sqlalchemy.orm import Session

from newsroom.control.manager import ImportResult, NewsroomControl
from newsroom.storage.models import Source, SourceInventory

SOURCE_MODES = frozenset({"empty", "default", "custom"})


@dataclass(frozen=True)
class CatalogEntry:
    key: str
    name: str
    source_type: str
    url: str
    language: str
    category: str
    trust_class: str
    default_enabled: bool


@dataclass(frozen=True)
class CatalogApplyResult:
    mode: str
    available: int
    selected: int
    created: int
    updated: int
    skipped: int
    disabled_existing: int
    errors: tuple[str, ...]


class SourceCatalog:
    """Initialize and inspect source registries through one small interface."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def available(self) -> tuple[CatalogEntry, ...]:
        """Return the packaged, credential-free starter entries."""
        resource = files("newsroom.resources").joinpath("sources.default.csv")
        text = resource.read_text(encoding="utf-8")
        rows = csv.DictReader(io.StringIO(text))
        return tuple(_entry_from_row(row) for row in rows)

    def apply(
        self,
        mode: str,
        *,
        selection: tuple[str, ...] = (),
        custom_file: Path | None = None,
        replace: bool = False,
    ) -> CatalogApplyResult:
        """Apply an empty, default, or custom source configuration.

        ``replace`` is non-destructive: it disables existing sources but keeps
        their items, cursors, and lineage. Applying the same configuration is
        idempotent.
        """
        normalized_mode = mode.strip().lower()
        if normalized_mode not in SOURCE_MODES:
            raise ValueError("source mode must be one of: empty, default, custom")
        disabled_existing = self._disable_existing() if replace else 0

        if normalized_mode == "empty":
            if selection or custom_file is not None:
                raise ValueError("empty source mode does not accept a selection or file")
            return CatalogApplyResult(
                mode=normalized_mode,
                available=len(self.available()),
                selected=0,
                created=0,
                updated=0,
                skipped=0,
                disabled_existing=disabled_existing,
                errors=(),
            )

        if normalized_mode == "custom":
            if selection:
                raise ValueError("custom source mode does not accept starter keys")
            if custom_file is None:
                raise ValueError("custom source mode requires --file")
            import_result = self._import_path(custom_file)
            return _apply_result(
                normalized_mode,
                available=len(self.available()),
                selected=import_result.total_rows,
                disabled_existing=disabled_existing,
                imported=import_result,
            )

        if custom_file is not None:
            raise ValueError("default source mode does not accept --file")
        entries = self.available()
        selected_entries = _select_entries(entries, selection)
        import_result = NewsroomControl(self.db).import_sources(
            "sources.default.csv",
            _entries_as_import_csv(selected_entries),
        )
        return _apply_result(
            normalized_mode,
            available=len(entries),
            selected=len(selected_entries),
            disabled_existing=disabled_existing,
            imported=import_result,
        )

    def _disable_existing(self) -> int:
        sources = self.db.query(Source).filter(Source.enabled.is_(True)).all()
        source_ids = [source.id for source in sources]
        for source in sources:
            source.enabled = False
            source.inactive_reason = "replaced_by_setup"
        if source_ids:
            inventory_rows = (
                self.db.query(SourceInventory)
                .filter(SourceInventory.source_id.in_(source_ids))
                .all()
            )
            for row in inventory_rows:
                row.operational_state = "inactive"
                row.inactive_reason = "replaced_by_setup"
        self.db.flush()
        return len(sources)

    def _import_path(self, path: Path) -> ImportResult:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise ValueError(f"source file does not exist: {path}")
        return NewsroomControl(self.db).import_sources(
            resolved.name,
            resolved.read_bytes(),
        )


def _entry_from_row(row: dict[str, str]) -> CatalogEntry:
    required = ("key", "name", "type", "url")
    missing = [field for field in required if not str(row.get(field) or "").strip()]
    if missing:
        raise ValueError(f"starter catalog row is missing: {', '.join(missing)}")
    return CatalogEntry(
        key=row["key"].strip().lower(),
        name=row["name"].strip(),
        source_type=row["type"].strip().lower(),
        url=row["url"].strip(),
        language=(row.get("language") or "en").strip().lower(),
        category=(row.get("category") or "general").strip(),
        trust_class=(row.get("trust_class") or "community").strip(),
        default_enabled=(row.get("default_enabled") or "").strip().lower()
        in {"1", "true", "yes", "on"},
    )


def _select_entries(
    entries: tuple[CatalogEntry, ...],
    selection: tuple[str, ...],
) -> tuple[CatalogEntry, ...]:
    if not selection:
        return tuple(entry for entry in entries if entry.default_enabled)
    requested = {key.strip().lower() for key in selection if key.strip()}
    available = {entry.key: entry for entry in entries}
    unknown = sorted(requested - available.keys())
    if unknown:
        raise ValueError(f"unknown starter source keys: {', '.join(unknown)}")
    return tuple(entry for entry in entries if entry.key in requested)


def _entries_as_import_csv(entries: tuple[CatalogEntry, ...]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=(
            "name",
            "type",
            "url",
            "language",
            "category",
            "trust_class",
            "enabled",
        ),
    )
    writer.writeheader()
    for entry in entries:
        writer.writerow(
            {
                "name": entry.name,
                "type": entry.source_type,
                "url": entry.url,
                "language": entry.language,
                "category": entry.category,
                "trust_class": entry.trust_class,
                # Explicit selection means explicit activation.
                "enabled": "true",
            }
        )
    return stream.getvalue().encode("utf-8")


def _apply_result(
    mode: str,
    *,
    available: int,
    selected: int,
    disabled_existing: int,
    imported: ImportResult,
) -> CatalogApplyResult:
    return CatalogApplyResult(
        mode=mode,
        available=available,
        selected=selected,
        created=imported.created,
        updated=imported.updated,
        skipped=imported.skipped,
        disabled_existing=disabled_existing,
        errors=imported.errors,
    )
