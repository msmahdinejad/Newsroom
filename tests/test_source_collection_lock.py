"""Cross-worker source persistence lock."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from newsroom.pipeline.source_lock import acquire_source_collection_lock


def test_postgres_source_lock_uses_bounded_two_key_namespace() -> None:
    session = MagicMock()
    session.get_bind.return_value = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql")
    )

    acquire_source_collection_lock(session, 42)

    params = session.execute.call_args.args[1]
    assert params == {"namespace": 0x4E575352, "source_id": 42}


def test_source_lock_is_noop_outside_postgres() -> None:
    session = MagicMock()
    session.get_bind.return_value = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    acquire_source_collection_lock(session, 42)

    session.execute.assert_not_called()
