"""Command-line interface."""

import argparse
import asyncio
import sys

from sqlalchemy import text

from newsroom.logging import get_logger, setup_logging
from newsroom.storage.database import engine

logger = get_logger(__name__)


def health_check() -> int:
    """Check system health."""
    setup_logging()
    logger.info("Running health check")

    try:
        # Check database connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        logger.info("Database connection: OK")

        # Check tables exist
        from newsroom.storage.models import Base
        with engine.connect() as conn:
            for table in Base.metadata.tables:
                conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
        logger.info("Database tables: OK")

        print("✓ All health checks passed")
        return 0

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        print(f"✗ Health check failed: {e}")
        return 1


def db_migrate() -> int:
    """Run database migrations."""
    setup_logging()
    logger.info("Running database migrations")

    try:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")

        logger.info("Migrations completed successfully")
        print("✓ Database migrations applied")
        return 0

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        print(f"✗ Migration failed: {e}")
        return 1


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Persian AI Newsroom")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Health command
    subparsers.add_parser("health", help="Check system health")

    # Database commands
    db_parser = subparsers.add_parser("db", help="Database management")
    db_subparsers = db_parser.add_subparsers(dest="db_command")
    db_subparsers.add_parser("migrate", help="Run database migrations")

    # Collect command
    collect_parser = subparsers.add_parser("collect", help="Collect from sources")
    collect_parser.add_argument(
        "--source-type",
        choices=["rss", "github_releases"],
        help="Filter by source type"
    )

    # Process commands
    process_parser = subparsers.add_parser("process", help="Processing pipeline")
    process_subparsers = process_parser.add_subparsers(dest="process_command")

    normalize_parser = process_subparsers.add_parser("normalize", help="Normalize raw items")
    normalize_parser.add_argument("--limit", type=int, default=100, help="Max items to process")

    dedupe_parser = process_subparsers.add_parser("dedupe", help="Deduplicate items")
    dedupe_parser.add_argument("--limit", type=int, default=1000, help="Max items to check")

    cluster_parser = process_subparsers.add_parser("cluster", help="Cluster into stories")
    cluster_parser.add_argument("--limit", type=int, default=1000, help="Max items to cluster")

    # Digest commands
    digest_parser = subparsers.add_parser("digest", help="Digest generation")
    digest_subparsers = digest_parser.add_subparsers(dest="digest_command")

    preview_parser = digest_subparsers.add_parser("preview", help="Generate preview")
    preview_parser.add_argument("--limit", type=int, default=50, help="Max stories")
    preview_parser.add_argument("--save", action="store_true", help="Save to database")

    # Pipeline command
    pipeline_parser = subparsers.add_parser("pipeline", help="Run complete pipeline")
    pipeline_subparsers = pipeline_parser.add_subparsers(dest="pipeline_command")
    pipeline_subparsers.add_parser("run", help="Run full collection→digest pipeline")

    args = parser.parse_args()

    # Route to handlers
    if args.command == "health":
        return health_check()
    elif args.command == "db" and args.db_command == "migrate":
        return db_migrate()
    elif args.command == "collect":
        from newsroom.cli.commands.collect import collect_command
        return asyncio.run(collect_command(args))
    elif args.command == "process":
        from newsroom.cli.commands.process import (
            cluster_command,
            dedupe_command,
            normalize_command,
        )
        if args.process_command == "normalize":
            return normalize_command(args)
        elif args.process_command == "dedupe":
            return dedupe_command(args)
        elif args.process_command == "cluster":
            return cluster_command(args)
    elif args.command == "digest":
        from newsroom.cli.commands.digest import preview_command
        if args.digest_command == "preview":
            return preview_command(args)
    elif args.command == "pipeline" and args.pipeline_command == "run":
        from newsroom.cli.commands.pipeline import pipeline_run_command
        return asyncio.run(pipeline_run_command(args))
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
