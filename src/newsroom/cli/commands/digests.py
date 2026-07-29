"""Named digest command adapter."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from newsroom.control import DigestCatalog, DigestUpdate
from newsroom.logging import setup_logging
from newsroom.storage.database import get_db


def digests_command(args: argparse.Namespace) -> int:
    """Dispatch digest administration through the domain interface."""
    setup_logging()
    action = getattr(args, "digests_command", None)
    try:
        with get_db() as db:
            catalog = DigestCatalog(db)
            if action == "list":
                value: object = [asdict(item) for item in catalog.list()]
            elif action == "show":
                value = asdict(catalog.get(args.slug))
            elif action == "create":
                value = asdict(
                    catalog.create(
                        slug=args.slug,
                        name=args.name,
                        topic_brief=args.topic,
                        output_language=args.language,
                        timezone=args.timezone,
                    )
                )
            elif action == "update":
                value = asdict(catalog.update(args.slug, _update_from_args(args)))
            elif action in {"enable", "disable"}:
                value = asdict(
                    catalog.update(
                        args.slug,
                        DigestUpdate(enabled=action == "enable"),
                    )
                )
            else:
                raise ValueError("a digest subcommand is required")
        print(json.dumps(value, ensure_ascii=True, indent=2, default=str))
        return 0
    except (LookupError, TypeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2


def _update_from_args(args: argparse.Namespace) -> DigestUpdate:
    schedule = _csv(args.schedule) if args.schedule is not None else None
    schedule_enabled = None
    if schedule == ("off",):
        schedule = ()
        schedule_enabled = False
    return DigestUpdate(
        name=args.name,
        topic_brief=args.topic,
        include_terms=_csv(args.include) if args.include is not None else None,
        exclude_terms=_csv(args.exclude) if args.exclude is not None else None,
        output_language=args.language,
        timezone=args.timezone,
        source_groups=_csv(args.sources) if args.sources is not None else None,
        source_ids=(
            tuple(int(item) for item in _csv(args.source_ids))
            if args.source_ids is not None
            else None
        ),
        max_stories=args.count,
        minimum_telegram_stories=args.telegram_min,
        schedule_times=schedule,
        schedule_enabled=schedule_enabled,
    )


def _csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())
