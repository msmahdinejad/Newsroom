"""Newsroom command-line interface."""

import argparse
import asyncio
import sys

from newsroom.logging import get_logger, setup_logging
from newsroom.storage.database import db_health

logger = get_logger(__name__)


def health_check() -> int:
    """Check system health."""
    setup_logging()
    if db_health():
        print("OK: database healthy")
        return 0
    print("FAIL: database not reachable")
    return 1


def db_migrate() -> int:
    """Run database migrations."""
    setup_logging()
    try:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        print("OK: migrations applied")
        return 0
    except Exception as e:
        print(f"FAIL: migration failed: {e}")
        return 1


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Newsroom")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("health", help="Check system health")

    db_parser = subparsers.add_parser("db", help="Database management")
    db_sub = db_parser.add_subparsers(dest="db_command")
    db_sub.add_parser("migrate", help="Run migrations")

    collect_parser = subparsers.add_parser("collect", help="Collect from sources")
    collect_parser.add_argument("--source-type", choices=["rss", "github_releases"], default=None)

    process_parser = subparsers.add_parser("process", help="Processing pipeline")
    process_sub = process_parser.add_subparsers(dest="process_command")
    process_sub.add_parser("all", help="Run all processing stages")
    process_sub.add_parser("normalize", help="Normalize raw items")
    process_sub.add_parser("dedupe", help="Deduplicate items")
    process_sub.add_parser("cluster", help="Cluster into stories")
    process_sub.add_parser(
        "repair-clusters",
        help="Split legacy clusters polluted by feed boilerplate",
    )

    report_parser = subparsers.add_parser("report", help="Report generation")
    report_sub = report_parser.add_subparsers(dest="report_command")
    report_generate = report_sub.add_parser("generate", help="Generate a localized report")
    report_generate.add_argument(
        "--source",
        choices=["default", "all", "telegram", "x", "web", "github", "reddit"],
        default="default",
        help="Scope the configured digest to one supported platform",
    )
    report_generate.add_argument(
        "--digest",
        default="default",
        help="Digest slug to generate",
    )

    digests_parser = subparsers.add_parser(
        "digests",
        help="Create and configure named news digests",
    )
    digests_sub = digests_parser.add_subparsers(dest="digests_command")
    digests_sub.add_parser("list", help="List digest definitions")
    digest_show = digests_sub.add_parser("show", help="Show one digest")
    digest_show.add_argument("slug")
    digest_create = digests_sub.add_parser("create", help="Create a digest")
    digest_create.add_argument("slug")
    digest_create.add_argument("--name", required=True)
    digest_create.add_argument("--topic", required=True)
    digest_create.add_argument("--language", choices=["fa", "en"], default="fa")
    digest_create.add_argument("--timezone", default="Asia/Tehran")
    digest_update = digests_sub.add_parser("update", help="Update a digest")
    digest_update.add_argument("slug")
    digest_update.add_argument("--name")
    digest_update.add_argument("--topic")
    digest_update.add_argument("--include")
    digest_update.add_argument("--exclude")
    digest_update.add_argument("--language", choices=["fa", "en"])
    digest_update.add_argument("--timezone")
    digest_update.add_argument("--sources")
    digest_update.add_argument("--source-ids")
    digest_update.add_argument("--count", type=int)
    digest_update.add_argument("--telegram-min", type=int)
    digest_update.add_argument("--schedule")
    for action in ("enable", "disable"):
        digest_action = digests_sub.add_parser(
            action,
            help=f"{action.title()} one digest",
        )
        digest_action.add_argument("slug")

    pipeline_parser = subparsers.add_parser("pipeline", help="Run complete pipeline")
    pipeline_sub = pipeline_parser.add_subparsers(dest="pipeline_command")
    pipeline_sub.add_parser("run", help="Run full pipeline")

    providers_parser = subparsers.add_parser(
        "providers",
        help="Editorial provider validation and safe health",
    )
    providers_sub = providers_parser.add_subparsers(dest="providers_command")
    providers_validate = providers_sub.add_parser(
        "validate",
        help="Run bounded validation for configured models",
    )
    providers_validate.add_argument(
        "--provider",
        help="Configured provider name; omit to validate every configured provider",
    )
    providers_validate.add_argument(
        "--model",
        action="append",
        help="Exact provider model ID; repeat to validate multiple models",
    )
    providers_validate.add_argument(
        "--validate-keys",
        action="store_true",
        help="Also probe each configured key through a validated route",
    )
    providers_validate.add_argument(
        "--discover",
        action="store_true",
        help="Discover generation-capable model IDs, then validate them before enabling",
    )
    providers_validate.add_argument(
        "--max-discovered-models",
        type=int,
        default=50,
        help="Bound discovered model validation per provider (1..100)",
    )
    providers_discover = providers_sub.add_parser(
        "discover",
        help="List generation-capable provider model IDs without enabling them",
    )
    providers_discover.add_argument("--provider")
    providers_discover.add_argument("--max-models", type=int, default=50)
    providers_sub.add_parser("status", help="Show persisted safe provider health")

    sources_parser = subparsers.add_parser("sources", help="Source registry management")
    sources_sub = sources_parser.add_subparsers(dest="sources_command")

    sources_sub.add_parser("catalog", help="List packaged starter sources")
    sources_initialize = sources_sub.add_parser(
        "initialize",
        help="Initialize an empty, default, or custom source registry",
    )
    sources_initialize.add_argument(
        "--mode",
        choices=["empty", "default", "custom"],
        required=True,
    )
    sources_initialize.add_argument("--file", help="CSV/XLSX file for custom mode")
    sources_initialize.add_argument(
        "--select",
        help="Comma-separated starter keys; omit to use the default subset",
    )
    sources_initialize.add_argument(
        "--replace",
        action="store_true",
        help="Disable existing sources before applying the selection",
    )

    sources_import = sources_sub.add_parser("import", help="Import a CSV/XLSX source file")
    sources_import.add_argument("--file", required=True)
    sources_add = sources_sub.add_parser(
        "add",
        help="Add one source from a supported platform",
    )
    sources_add.add_argument("--name", required=True)
    sources_add.add_argument(
        "--type",
        required=True,
        choices=[
            "telegram",
            "x_timeline",
            "reddit_subreddit",
            "github_releases",
            "rss",
            "web_page",
        ],
    )
    sources_add.add_argument("--url", required=True)
    sources_add.add_argument("--language", default="en")
    sources_add.add_argument("--category", default="general")
    sources_add.add_argument(
        "--enable",
        action="store_true",
        help="Activate immediately; otherwise leave pending operator review",
    )
    sources_list = sources_sub.add_parser("list", help="List configured sources")
    sources_list.add_argument("--type")
    sources_list.add_argument("--enabled", choices=["all", "yes", "no"], default="all")
    sources_list.add_argument("--page", type=int, default=1)
    sources_list.add_argument("--page-size", type=int, default=20)
    for action in ("enable", "disable"):
        source_action = sources_sub.add_parser(action, help=f"{action.title()} one source")
        source_action.add_argument("source_id", type=int)
    source_delete = sources_sub.add_parser(
        "delete",
        help="Archive one source while retaining collected lineage",
    )
    source_delete.add_argument("source_id", type=int)
    source_delete.add_argument("--confirm", action="store_true", required=True)

    source_discover = sources_sub.add_parser(
        "discover",
        help="Find grounded candidates with Gemini Search; approval is separate",
    )
    source_discover.add_argument("--subject", required=True)
    source_discover.add_argument(
        "--platforms",
        default="all",
        help="Comma-separated: telegram,x,reddit,github,web",
    )
    source_discover.add_argument("--mode", choices=["quick", "deep"], default="quick")
    source_discover.add_argument("--max-candidates", type=int, default=20)
    discovery_poll = sources_sub.add_parser(
        "discovery-poll",
        help="Poll a background deep-research discovery job",
    )
    discovery_poll.add_argument("job_id", type=int)
    discovery_poll.add_argument("--max-candidates", type=int, default=20)
    discovery_candidates = sources_sub.add_parser(
        "candidates",
        help="List discovered candidates awaiting an operator decision",
    )
    discovery_candidates.add_argument("--job", type=int)
    discovery_candidates.add_argument(
        "--status",
        choices=["pending", "approved", "rejected"],
    )
    for action in ("approve", "reject"):
        candidate_action = sources_sub.add_parser(
            action,
            help=f"{action.title()} one discovered candidate",
        )
        candidate_action.add_argument("candidate_id", type=int)

    inventory_import = sources_sub.add_parser(
        "inventory-import",
        help="Import the optional extended inventory workbook",
    )
    inventory_import.add_argument(
        "--workbook",
        help="Workbook path (or set NEWSROOM_SOURCE_WORKBOOK)",
    )
    sources_sub.add_parser(
        "inventory-activate",
        help="Activate usable rows from the extended inventory",
    )
    inventory_reconcile = sources_sub.add_parser(
        "inventory-reconcile",
        help="Import and activate an extended inventory",
    )
    inventory_reconcile.add_argument(
        "--workbook",
        help="Workbook path (or set NEWSROOM_SOURCE_WORKBOOK)",
    )
    sources_sub.add_parser(
        "inventory-status",
        help="Show extended-inventory reconciliation status",
    )

    args = parser.parse_args()

    if args.command == "health":
        return health_check()
    elif args.command == "db" and args.db_command == "migrate":
        return db_migrate()
    elif args.command == "collect":
        from newsroom.cli.commands.collect import collect_command

        return asyncio.run(collect_command(args))
    elif args.command == "process":
        from newsroom.cli.commands.process import process_command

        return process_command(args)
    elif args.command == "report" and args.report_command == "generate":
        from newsroom.cli.commands.report import report_command

        return report_command(args)
    elif args.command == "digests":
        from newsroom.cli.commands.digests import digests_command

        return digests_command(args)
    elif args.command == "pipeline" and args.pipeline_command == "run":
        from newsroom.cli.commands.pipeline import pipeline_run_command

        return pipeline_run_command(args)
    elif args.command == "providers":
        from newsroom.cli.commands.providers import providers_command

        return providers_command(args)
    elif args.command == "sources":
        from newsroom.cli.commands.sources import sources_command

        return sources_command(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
