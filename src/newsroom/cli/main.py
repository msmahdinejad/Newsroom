"""Command-line interface."""

import argparse
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

    args = parser.parse_args()

    if args.command == "health":
        return health_check()
    elif args.command == "db" and args.db_command == "migrate":
        return db_migrate()
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
