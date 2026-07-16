"""PostgreSQL session-level advisory lock for the report pipeline.

One owner across containers/processes. Held on a dedicated connection for
the full pipeline duration. Connection close (crash/exit) releases the lock.
JobRun rows are tracking only — never treated as locks.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import socket
import uuid
from types import TracebackType

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from newsroom.config import settings

# Stable 64-bit key derived from lock name (pg_try_advisory_lock takes bigint).
_LOCK_NAME = "newsroom_report_pipeline"
_LOCK_KEY = int.from_bytes(hashlib.sha256(_LOCK_NAME.encode()).digest()[:8], "big", signed=True)


class PipelineBusyError(Exception):
    """Another process holds the pipeline lock."""

    def __init__(self, owner_hint: str = "") -> None:
        self.owner_hint = owner_hint
        super().__init__(f"pipeline busy{f' (held by {owner_hint})' if owner_hint else ''}")


def owner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class PipelineLock:
    """Context manager: try-acquire session advisory lock on a dedicated connection."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        blocking: bool = False,
        owner: str | None = None,
    ) -> None:
        self.database_url = database_url or str(settings.database_url)
        self.blocking = blocking
        self.owner = owner or owner_id()
        self._engine: Engine | None = None
        self._conn: Connection | None = None
        self.acquired = False

    def __enter__(self) -> PipelineLock:
        self._engine = create_engine(
            self.database_url,
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
        )
        self._conn = self._engine.connect()
        self._conn = self._conn.execution_options(isolation_level="AUTOCOMMIT")
        fn = "pg_advisory_lock" if self.blocking else "pg_try_advisory_lock"
        row = self._conn.execute(text(f"SELECT {fn}(:k)"), {"k": _LOCK_KEY}).scalar()
        self.acquired = True if self.blocking else bool(row)
        if not self.acquired:
            self._close()
            raise PipelineBusyError(self.owner)
        self._conn.execute(
            text("SELECT set_config('newsroom.pipeline_owner', :owner, false)"),
            {"owner": self.owner[:200]},
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if self.acquired and self._conn is not None:
                self._conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
        finally:
            self._close()
            self.acquired = False

    def _close(self) -> None:
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.close()
            self._conn = None
        if self._engine is not None:
            with contextlib.suppress(Exception):
                self._engine.dispose()
            self._engine = None


def try_acquire_status(database_url: str | None = None) -> dict:
    """Probe lock without holding it (opens, tries, unlocks). For health/tests."""
    try:
        with PipelineLock(database_url=database_url) as lock:
            return {"status": "acquired", "owner": lock.owner, "key": _LOCK_KEY}
    except PipelineBusyError as e:
        return {"status": "busy", "owner_hint": e.owner_hint, "key": _LOCK_KEY}
