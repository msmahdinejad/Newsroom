"""Database connection and session management."""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from newsroom.config import settings

# ponytail: NullPool avoids connection pooling hangs on Windows
engine = create_engine(
    str(settings.database_url),
    pool_pre_ping=True,
    echo=False,
)

session_factory = sessionmaker(bind=engine)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Get database session — auto commit/rollback."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def db_health() -> bool:
    """Quick connectivity check."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
