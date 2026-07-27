"""Isolated PostgreSQL fixtures for integration tests."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_ENV = "NEWSROOM_TEST_DATABASE_URL"
TEST_DATABASE_NAME = "newsroom_test"

_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _configured_application_url() -> str:
    explicit_test_url = os.environ.get(TEST_DATABASE_ENV)
    if explicit_test_url:
        return explicit_test_url
    ambient_url = os.environ.get("DATABASE_URL")
    if ambient_url:
        return ambient_url
    local_values = dotenv_values(ROOT / ".env", interpolate=False)
    return str(
        local_values.get("DATABASE_URL")
        or (
            "postgresql+psycopg://newsroom:newsroom_dev@"
            "127.0.0.1:55432/newsroom"
        )
    )


def _isolated_test_url() -> URL:
    configured = make_url(_configured_application_url())
    if os.environ.get(TEST_DATABASE_ENV) or os.environ.get("DATABASE_URL"):
        database = configured.database or ""
        if not re.fullmatch(r"[A-Za-z0-9_]*_test", database):
            raise pytest.UsageError(
                "integration tests require DATABASE_URL or "
                "NEWSROOM_TEST_DATABASE_URL to target a *_test database"
            )
        return configured
    return configured.set(database=TEST_DATABASE_NAME)


TEST_URL = _isolated_test_url()
os.environ["DATABASE_URL"] = TEST_URL.render_as_string(hide_password=False)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: real PostgreSQL tests")


@pytest.fixture(scope="session", autouse=True)
def isolated_database() -> Generator[None, None, None]:
    """Create a fresh test-only database, migrate it, then remove it."""
    database = TEST_URL.database or ""
    if not re.fullmatch(r"[A-Za-z0-9_]*_test", database):
        raise pytest.UsageError("refusing to manage a database without a *_test suffix")
    admin_url = TEST_URL.set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    quoted_database = f'"{database}"'
    with admin.connect() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :database AND pid <> pg_backend_pid()"
            ),
            {"database": database},
        )
        connection.exec_driver_sql(f"DROP DATABASE IF EXISTS {quoted_database}")
        connection.exec_driver_sql(f"CREATE DATABASE {quoted_database}")

    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )
    if migration.returncode:
        raise pytest.UsageError(
            f"test database migration failed: {migration.stderr.strip()}"
        )
    try:
        yield
    finally:
        with admin.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database AND pid <> pg_backend_pid()"
                ),
                {"database": database},
            )
            connection.exec_driver_sql(f"DROP DATABASE IF EXISTS {quoted_database}")
        admin.dispose()


@pytest.fixture(scope="session")
def database_url(isolated_database: None) -> str:
    return TEST_URL.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def engine(database_url: str) -> Generator[Engine, None, None]:
    eng = create_engine(database_url, pool_pre_ping=True)
    with eng.connect() as connection:
        connection.execute(text("SELECT 1"))
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
        session.rollback()
    finally:
        session.close()
