"""Gate 2 schema integration tests — verify migration 0003 creates correct tables."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect, text

pytestmark = pytest.mark.integration

DEFAULT_URL = "postgresql+psycopg://newsroom:newsroom_dev@127.0.0.1:55432/newsroom"


def test_gate2_tables_exist():
    """Migration 0003 created telegram_updates, delivery_chunks, report_cursors, command_requests."""
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    eng = create_engine(url, pool_pre_ping=True)
    insp = inspect(eng)
    tables = insp.get_table_names()

    assert "telegram_updates" in tables
    assert "delivery_chunks" in tables
    assert "report_cursors" in tables
    assert "command_requests" in tables

    # Verify deliveries has new columns
    delivery_cols = {c["name"] for c in insp.get_columns("deliveries")}
    assert "chat_ref" in delivery_cols
    assert "attempt_count" in delivery_cols
    assert "retry_count" in delivery_cols
    assert "error_category" in delivery_cols
    assert "parse_mode" in delivery_cols
    assert "last_send_at" in delivery_cols

    eng.dispose()


def test_telegram_updates_unique_update_id():
    """telegram_updates.update_id has unique index."""
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    eng = create_engine(url, pool_pre_ping=True)
    insp = inspect(eng)

    indexes = insp.get_indexes("telegram_updates")
    unique_indexes = [i for i in indexes if i["unique"]]
    assert any(i["column_names"] == ["update_id"] for i in unique_indexes)

    eng.dispose()


def test_delivery_chunks_unique_index():
    """delivery_chunks has unique constraint on (delivery_id, chunk_index)."""
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    eng = create_engine(url, pool_pre_ping=True)
    insp = inspect(eng)

    constraints = insp.get_unique_constraints("delivery_chunks")
    col_sets = [frozenset(c["column_names"]) for c in constraints]
    assert frozenset({"delivery_id", "chunk_index"}) in col_sets

    eng.dispose()


def test_report_cursor_seeded():
    """report_cursors has 'scheduled_delivery' row seeded."""
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    eng = create_engine(url, pool_pre_ping=True)
    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT cursor_key FROM report_cursors WHERE cursor_key = 'scheduled_delivery'")
        ).first()
    assert row is not None
    assert row[0] == "scheduled_delivery"
    eng.dispose()


def test_command_requests_unique_request_key():
    """command_requests.request_key has unique index."""
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    eng = create_engine(url, pool_pre_ping=True)
    insp = inspect(eng)

    indexes = insp.get_indexes("command_requests")
    unique_indexes = [i for i in indexes if i["unique"]]
    assert any(i["column_names"] == ["request_key"] for i in unique_indexes)

    eng.dispose()


def test_alembic_at_gate2_revision():
    """Alembic head should be at or past 0003_gate2_telegram."""
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    eng = create_engine(url, pool_pre_ping=True)
    with eng.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
    assert row is not None
    assert row[0] == "0003_gate2_telegram"
    eng.dispose()
