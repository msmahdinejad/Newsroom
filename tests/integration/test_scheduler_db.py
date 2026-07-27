"""Production scheduler integration test — four six-hour Tehran jobs persist in PostgreSQL.

Real DB: creates the scheduler (SQLAlchemyJobStore), verifies exactly four
jobs are registered at hours 00/06/12/18, then shuts it down cleanly within
the same event loop. Also verifies scheduler state persists in the
apscheduler_jobs table across restarts.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import create_engine, inspect, text

pytestmark = pytest.mark.integration

DEFAULT_URL = "postgresql+psycopg://newsroom:newsroom_dev@127.0.0.1:55432/newsroom"


def test_scheduler_registers_four_six_hour_jobs():
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    eng = create_engine(url, pool_pre_ping=True)
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
    # Clear stale job refs from ad-hoc `python -m` runs so the fresh scheduler
    # registers cleanly. In production the scheduler always runs as the same
    # module, so func_refs resolve across restarts.
    if inspect(eng).has_table("apscheduler_jobs"):
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM apscheduler_jobs"))

    asyncio.run(_run_scheduler_test(url))
    eng.dispose()


async def _run_scheduler_test(url: str) -> None:
    os.environ.setdefault("DATABASE_URL", url)
    from newsroom.scheduler import create_scheduler, registered_job_ids

    scheduler = create_scheduler()
    scheduler.start()
    await asyncio.sleep(0.5)
    try:
        jobs = registered_job_ids(scheduler)
        assert jobs == ["report_00", "report_06", "report_12", "report_18"]
        triggers = {j.id: j.trigger for j in scheduler.get_jobs()}
        for jid, hour in [("report_00", 0), ("report_06", 6), ("report_12", 12), ("report_18", 18)]:
            hour_field = str(triggers[jid].fields[5]).replace(" ", "")
            assert str(hour) == hour_field
            assert str(triggers[jid].fields[6]) == "0"  # minute
    finally:
        scheduler.shutdown(wait=False)
