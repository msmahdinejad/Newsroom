"""Cross-process advisory lock — independent connections, not threads-only."""

from __future__ import annotations

import multiprocessing as mp
import os
import time

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration

DEFAULT_URL = "postgresql+psycopg://newsroom:newsroom_dev@127.0.0.1:55432/newsroom"


def _hold_lock(url: str, hold_s: float, q: mp.Queue) -> None:
    """Child process: acquire lock, signal, hold, release."""
    import sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src"
    sys.path.insert(0, str(src))
    from newsroom.pipeline.lock import PipelineBusyError, PipelineLock

    try:
        with PipelineLock(database_url=url, owner="child_holder") as lock:
            q.put({"event": "acquired", "owner": lock.owner})
            time.sleep(hold_s)
            q.put({"event": "released"})
    except PipelineBusyError as e:
        q.put({"event": "busy", "error": str(e)})
    except Exception as e:
        q.put({"event": "error", "error": str(e)})


def _try_lock(url: str, q: mp.Queue) -> None:
    import sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src"
    sys.path.insert(0, str(src))
    from newsroom.pipeline.lock import PipelineBusyError, PipelineLock

    try:
        with PipelineLock(database_url=url, owner="child_contender"):
            q.put({"event": "acquired_unexpected"})
    except PipelineBusyError:
        q.put({"event": "busy"})
    except Exception as e:
        q.put({"event": "error", "error": str(e)})


def test_second_connection_gets_busy() -> None:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    ctx = mp.get_context("spawn")
    q: mp.Queue = ctx.Queue()
    holder = ctx.Process(target=_hold_lock, args=(url, 3.0, q))
    holder.start()
    first = q.get(timeout=10)
    assert first["event"] == "acquired", first

    contender = ctx.Process(target=_try_lock, args=(url, q))
    contender.start()
    second = q.get(timeout=10)
    assert second["event"] == "busy", second
    contender.join(timeout=5)
    holder.join(timeout=10)
    assert contender.exitcode == 0
    assert holder.exitcode == 0


def test_stale_lock_released_on_disconnect() -> None:
    """Crash simulation: connection dispose without unlock still frees advisory lock."""
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    eng = create_engine(url, pool_size=1, max_overflow=0)
    conn = eng.connect().execution_options(isolation_level="AUTOCOMMIT")
    # compute same key as lock module
    import hashlib

    key = int.from_bytes(
        hashlib.sha256(b"newsroom_report_pipeline").digest()[:8], "big", signed=True
    )
    ok = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
    assert ok is True
    # drop connection without unlock — PG releases session locks
    conn.close()
    eng.dispose()

    eng2 = create_engine(url, pool_size=1, max_overflow=0)
    conn2 = eng2.connect().execution_options(isolation_level="AUTOCOMMIT")
    ok2 = conn2.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
    assert ok2 is True
    conn2.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
    conn2.close()
    eng2.dispose()
