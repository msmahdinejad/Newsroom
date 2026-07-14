"""Test configuration and fixtures — DB-free.

V2 tests run without a running database. Where a function needs a DB
session, tests supply a mock session (MagicMock) so SQLAlchemy queries
return canned results. This keeps tests fast, deterministic, and runnable
in any environment.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure src/ is importable when running tests from the repo root.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture
def mock_db():
    """A MagicMock session. Configure .query(...).filter(...).all() per test."""
    session = MagicMock()
    # Default: queries return empty lists / None
    q = MagicMock()
    q.filter.return_value = q
    q.all.return_value = []
    q.first.return_value = None
    q.filter_by.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.join.return_value = q
    session.query.return_value = q
    return session
