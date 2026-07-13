"""Database connection and session management."""

from contextlib import contextmanager

from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from newsroom.config import settings

# ponytail: NullPool avoids connection pooling hangs on Windows
engine = create_engine(
    str(settings.database_url),
    poolclass=pool.NullPool,
    echo=False,
)

session_factory = sessionmaker(bind=engine)


@contextmanager
def get_db():
    """Get database session."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
