"""PostgreSQL integration fixtures — real DB, no MagicMock sessions.

Requires DATABASE_URL (or defaults to host-mapped 127.0.0.1:55432).
Uses a disposable schema/database when NEWSROOM_TEST_DB is set.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

# Ensure src is importable
_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

DEFAULT_URL = "postgresql+psycopg://newsroom:newsroom_dev@127.0.0.1:55432/newsroom"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: real PostgreSQL tests")


@pytest.fixture(scope="session")
def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


@pytest.fixture(scope="session")
def engine(database_url: str) -> Generator[Engine, None, None]:
    eng = create_engine(database_url, pool_pre_ping=True)
    # connectivity probe
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
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
