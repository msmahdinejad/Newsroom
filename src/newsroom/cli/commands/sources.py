"""Source catalog and registry command adapter."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from newsroom.control import NewsroomControl, SourceCatalog
from newsroom.logging import setup_logging
from newsroom.sources.inventory import (
    activate_inventory_sources,
    copy_workbook_to_import_dir,
    find_workbook,
    import_workbook,
    reconciliation_summary,
)
from newsroom.storage.database import get_db


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=True, indent=2, default=str))


def sources_command(args: argparse.Namespace) -> int:
    """Dispatch a source command through the control and catalog interfaces."""
    setup_logging()
    action = getattr(args, "sources_command", None)
    try:
        if action == "catalog":
            return _catalog()
        if action == "initialize":
            return _initialize(args)
        if action == "import":
            return _import_file(args.file)
        if action == "list":
            return _list_sources(args)
        if action in {"enable", "disable", "delete"}:
            return _change_source(args)
        if action == "inventory-import":
            return _inventory_import(args.workbook)
        if action == "inventory-activate":
            return _inventory_activate()
        if action == "inventory-reconcile":
            result = _inventory_import(args.workbook)
            return result if result else _inventory_activate()
        if action == "inventory-status":
            return _inventory_status()
    except (LookupError, TypeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print("FAIL: a source subcommand is required", file=sys.stderr)
    return 2


def _catalog() -> int:
    with get_db() as db:
        entries = SourceCatalog(db).available()
    _print([asdict(entry) for entry in entries])
    return 0


def _initialize(args: argparse.Namespace) -> int:
    selected = tuple(
        part.strip()
        for part in str(args.select or "").split(",")
        if part.strip()
    )
    source_file = Path(args.file) if args.file else None
    with get_db() as db:
        result = SourceCatalog(db).apply(
            args.mode,
            selection=selected,
            custom_file=source_file,
            replace=bool(args.replace),
        )
    _print(asdict(result))
    return 0 if not result.errors else 1


def _import_file(filename: str) -> int:
    path = Path(filename).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"source file does not exist: {filename}")
    with get_db() as db:
        result = NewsroomControl(db).import_sources(path.name, path.read_bytes())
    _print(asdict(result))
    return 0 if not result.errors else 1


def _list_sources(args: argparse.Namespace) -> int:
    enabled = {"yes": True, "no": False, "all": None}[args.enabled]
    with get_db() as db:
        rows, total = NewsroomControl(db).list_sources(
            source_type=args.type,
            enabled=enabled,
            page=args.page,
            page_size=args.page_size,
        )
        payload = [
            {
                "id": source.id,
                "name": source.name,
                "type": source.type,
                "url": source.url,
                "language": source.language,
                "enabled": source.enabled,
                "health": source.health_status,
                "inactive_reason": source.inactive_reason,
            }
            for source in rows
        ]
    _print({"page": args.page, "page_size": args.page_size, "total": total, "sources": payload})
    return 0


def _change_source(args: argparse.Namespace) -> int:
    with get_db() as db:
        control = NewsroomControl(db)
        if args.sources_command == "enable":
            result = control.set_source_enabled(args.source_id, True)
        elif args.sources_command == "disable":
            result = control.set_source_enabled(args.source_id, False)
        else:
            result = control.delete_source(args.source_id, confirmed=bool(args.confirm))
    _print(asdict(result))
    return 0


def _inventory_import(workbook: str | None) -> int:
    source = find_workbook(".", workbook)
    if source is None:
        raise ValueError(
            "inventory workbook not found; pass --workbook or set NEWSROOM_SOURCE_WORKBOOK"
        )
    destination = copy_workbook_to_import_dir(source, ".")
    with get_db() as db:
        report = import_workbook(db, destination)
    _print(report.to_dict())
    return 0


def _inventory_activate() -> int:
    with get_db() as db:
        report = activate_inventory_sources(db)
    _print(report.to_dict())
    return 0


def _inventory_status() -> int:
    with get_db() as db:
        summary = reconciliation_summary(db)
    _print(summary)
    return 0 if summary["reconciled"] else 1
