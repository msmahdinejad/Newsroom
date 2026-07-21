"""CLI command: source workbook import, activation, and reconciliation.

  newsroom sources import     locate + copy the workbook, import all rows
  newsroom sources activate   activate accessible sources into the registry
  newsroom sources reconcile   import + activate in one idempotent step
  newsroom sources status     print reconciliation and state summary

No manual database or YAML editing required.
"""

from __future__ import annotations

import argparse
import json
import sys

from newsroom.logging import get_logger, setup_logging
from newsroom.sources.inventory import (
    activate_inventory_sources,
    copy_workbook_to_import_dir,
    find_workbook,
    import_workbook,
    reconciliation_summary,
)
from newsroom.storage.database import get_db

logger = get_logger(__name__)


def _print(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def sources_command(args: argparse.Namespace) -> int:
    setup_logging()
    action = getattr(args, "sources_command", "status")
    if action == "import":
        return _do_import()
    if action == "activate":
        return _do_activate()
    if action == "reconcile":
        rc = _do_import()
        if rc != 0:
            return rc
        return _do_activate()
    if action == "status":
        return _do_status()
    print("unknown sources subcommand")
    return 1


def _do_import() -> int:
    src = find_workbook(".")
    if src is None:
        logger.error("workbook not found in searched paths")
        print(
            "FAIL: workbook not found. Searched: . config/import ~/OneDrive/Desktop",
            file=sys.stderr,
        )
        return 1
    dest = copy_workbook_to_import_dir(src, ".")
    logger.info(f"workbook copied: {src} -> {dest}")
    with get_db() as db:
        report = import_workbook(db, dest)
    _print(report.to_dict())
    print(f"[OK] imported {report.upserted} rows ({report.total_rows} total)")
    if report.duplicate_by_identity:
        print(f"[WARN] {report.duplicate_by_identity} duplicate stable identities skipped")
    if report.invalid:
        print(f"[WARN] {len(report.invalid)} invalid rows reported")
    return 0


def _do_activate() -> int:
    with get_db() as db:
        report = activate_inventory_sources(db)
    _print(report.to_dict())
    print(f"[OK] active={report.active} inactive={report.inactive} invalid={report.invalid} total={report.total}")
    return 0


def _do_status() -> int:
    with get_db() as db:
        summary = reconciliation_summary(db)
    _print(summary)
    ok = summary["reconciled"]
    print(f"[{'OK' if ok else 'WARN'}] total={summary['total']} expected={summary['expected']}")
    return 0 if ok else 1
