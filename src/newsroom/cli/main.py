"""Command-line interface — V2."""

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
    parser = argparse.ArgumentParser(description="Persian AI Newsroom v2")
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

    report_parser = subparsers.add_parser("report", help="Report generation")
    report_sub = report_parser.add_subparsers(dest="report_command")
    report_sub.add_parser("generate", help="Generate Persian report")

    pipeline_parser = subparsers.add_parser("pipeline", help="Run complete pipeline")
    pipeline_sub = pipeline_parser.add_subparsers(dest="pipeline_command")
    pipeline_sub.add_parser("run", help="Run full pipeline")

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
    elif args.command == "pipeline" and args.pipeline_command == "run":
        from newsroom.cli.commands.pipeline import pipeline_run_command
        return asyncio.run(pipeline_run_command(args))
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
