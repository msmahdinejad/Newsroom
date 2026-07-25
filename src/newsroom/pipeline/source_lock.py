"""Cross-worker PostgreSQL lock for one source persistence transaction."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

# Fixed int32 namespace ("NWSR") keeps source locks separate from other
# advisory-lock users while allowing the source id to remain the second key.
_SOURCE_LOCK_NAMESPACE = 0x4E575352


def acquire_source_collection_lock(session: Session, source_id: int) -> None:
    """Serialize check/dedup/insert/cursor work for one source on PostgreSQL."""
    try:
        dialect = session.get_bind().dialect.name
    except (AttributeError, TypeError):
        return
    if dialect != "postgresql":
        return
    session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :source_id)"),
        {"namespace": _SOURCE_LOCK_NAMESPACE, "source_id": int(source_id)},
    )


__all__ = ["acquire_source_collection_lock"]
