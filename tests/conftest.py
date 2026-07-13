"""Test configuration and fixtures."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from newsroom.config import settings


@pytest.fixture(scope="session")
def test_db_engine():
    """Create test database engine."""
    # Tables pre-created via SQL, skip DDL
    engine = create_engine(str(settings.database_url))
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(test_db_engine):
    """Provide a clean database session per test."""
    session_factory = sessionmaker(bind=test_db_engine)
    session = session_factory()
    yield session
    session.rollback()
    # ponytail: delete all test data to avoid IntegrityErrors between tests
    session.execute(text("TRUNCATE sources, raw_items, normalized_items, stories, digests CASCADE"))
    session.commit()
    session.close()
