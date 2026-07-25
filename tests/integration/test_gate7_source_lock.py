"""Real PostgreSQL verification for cross-worker source locks."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from newsroom.pipeline.source_lock import acquire_source_collection_lock

pytestmark = pytest.mark.integration

_NAMESPACE = 0x4E575352
_SOURCE_ID = 2_000_000_000


def test_source_lock_blocks_same_source_until_transaction_end(engine) -> None:
    with Session(engine) as first, Session(engine) as second:
        acquire_source_collection_lock(first, _SOURCE_ID)

        available_while_held = second.execute(
            text("SELECT pg_try_advisory_xact_lock(:namespace, :source_id)"),
            {"namespace": _NAMESPACE, "source_id": _SOURCE_ID},
        ).scalar_one()
        assert available_while_held is False

        first.rollback()
        available_after_release = second.execute(
            text("SELECT pg_try_advisory_xact_lock(:namespace, :source_id)"),
            {"namespace": _NAMESPACE, "source_id": _SOURCE_ID},
        ).scalar_one()
        assert available_after_release is True
        second.rollback()
