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
        if action == "add":
            return _add_source(args)
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
        if action == "discover":
            return _discover(args)
        if action == "discovery-poll":
            return _discovery_poll(args)
        if action == "candidates":
            return _discovery_candidates(args)
        if action in {"approve", "reject"}:
            return _decide_candidate(args)
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
    selected = tuple(part.strip() for part in str(args.select or "").split(",") if part.strip())
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


def _add_source(args: argparse.Namespace) -> int:
    with get_db() as db:
        result = NewsroomControl(db).add_source(
            name=args.name,
            source_type=args.type,
            url=args.url,
            language=args.language,
            category=args.category,
            enabled=bool(args.enable),
        )
    _print(asdict(result))
    return 0


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


def _discover(args: argparse.Namespace) -> int:
    from newsroom.sources.discovery import GeminiSourceDiscovery

    platforms = tuple(part.strip() for part in str(args.platforms).split(",") if part.strip())
    with get_db() as db:
        result = GeminiSourceDiscovery(db).start(
            subject=args.subject,
            platforms=platforms,
            mode=args.mode,
            max_candidates=args.max_candidates,
        )
    _print(asdict(result))
    return 0 if result.status in {"running", "completed"} else 1


def _discovery_poll(args: argparse.Namespace) -> int:
    from newsroom.sources.discovery import GeminiSourceDiscovery

    with get_db() as db:
        result = GeminiSourceDiscovery(db).poll(
            args.job_id,
            max_candidates=args.max_candidates,
        )
    _print(asdict(result))
    return 0 if result.status in {"running", "completed"} else 1


def _discovery_candidates(args: argparse.Namespace) -> int:
    from newsroom.sources.discovery import GeminiSourceDiscovery

    with get_db() as db:
        rows = GeminiSourceDiscovery(db).candidates(
            job_id=args.job,
            approval_status=args.status,
        )
        payload = [
            {
                "id": row.id,
                "job_id": row.job_id,
                "platform": row.platform,
                "type": row.source_type,
                "name": row.name,
                "url": row.normalized_url,
                "rationale": row.rationale,
                "score": row.score,
                "validation": row.validation_status,
                "failure_category": row.failure_category,
                "approval": row.approval_status,
                "source_id": row.source_id,
            }
            for row in rows
        ]
    _print(payload)
    return 0


def _decide_candidate(args: argparse.Namespace) -> int:
    from newsroom.sources.discovery import GeminiSourceDiscovery

    with get_db() as db:
        discovery = GeminiSourceDiscovery(db)
        row = (
            discovery.approve(args.candidate_id)
            if args.sources_command == "approve"
            else discovery.reject(args.candidate_id)
        )
        payload = {
            "id": row.id,
            "approval": row.approval_status,
            "source_id": row.source_id,
        }
    _print(payload)
    return 0
