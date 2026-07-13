"""Test configuration and fixtures."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from newsroom.storage.models import Base


@pytest.fixture(scope="session")
def test_db_engine():
    """Create test database engine."""
    # ponytail: uses main DB, separate test DB when needed
    engine = create_engine("postgresql+psycopg://newsroom:newsroom_dev@localhost:5432/newsroom")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(test_db_engine):
    """Provide a clean database session per test."""
    session_factory = sessionmaker(bind=test_db_engine)
    session = session_factory()
    yield session
    session.rollback()
    session.close()
