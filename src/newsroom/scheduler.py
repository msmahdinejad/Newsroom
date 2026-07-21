"""Persistent scheduler — APScheduler + SQLAlchemy job store, Asia/Tehran.

Jobs re-registered idempotently on startup (replace_existing=True).
Scheduled runs call the same newsroom.pipeline.runner path as manual CLI.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from newsroom.config import settings
from newsroom.logging import get_logger, setup_logging

logger = get_logger(__name__)

# Gate 6: four scheduled reports at six-hour boundaries (Tehran time).
# 00:00, 06:00, 12:00, 18:00 — independent of host/container timezone.
JOB_IDS = ("report_00", "report_06", "report_12", "report_18")
SCHEDULE_HOURS: tuple[int, ...] = (0, 6, 12, 18)


def scheduled_specs() -> list[tuple[str, int, int, str, str]]:
    """Return the (job_id, hour, minute, label, name) tuples for the four
    six-hour scheduled reports. Deterministic and testable without a DB."""
    return [
        (f"report_{h:02d}", h, 0, f"{h:02d}:00", f"Scheduled report ({h:02d}:00 Tehran)")
        for h in SCHEDULE_HOURS
    ]


async def run_scheduled_pipeline(job_label: str) -> None:
    """Invoke authoritative pipeline runner in-process (same lock/path as CLI)."""
    logger.info(f"Scheduled job triggered: {job_label}")
    os.environ["NEWSROOM_JOB_ID"] = (
        f"scheduled_{job_label}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    )
    os.environ["NEWSROOM_SCHEDULE_LABEL"] = job_label
    os.environ.setdefault("NEWSROOM_REPORT_MODE", "scheduled")

    from newsroom.pipeline.runner import EXIT_BUSY, run_pipeline

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, run_pipeline)
    status = result.get("status")
    if status == "busy" or result.get("exit_code") == EXIT_BUSY:
        logger.warning(f"Job {job_label}: pipeline busy (lock held)")
    else:
        logger.info(f"Job {job_label} finished: {status}")


def create_scheduler() -> AsyncIOScheduler:
    """Create scheduler with PostgreSQL job store and three Tehran cron jobs."""
    jobstores = {
        "default": SQLAlchemyJobStore(url=str(settings.database_url)),
    }
    scheduler = AsyncIOScheduler(
        timezone=settings.timezone or "Asia/Tehran",
        jobstores=jobstores,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 300,
        },
    )

    tz = settings.timezone or "Asia/Tehran"
    # Gate 6: six-hour reporting cadence at 00:00, 06:00, 12:00, 18:00 Tehran.
    for jid, hour, minute, label, name in scheduled_specs():
        scheduler.add_job(
            run_scheduled_pipeline,
            CronTrigger(hour=hour, minute=minute, timezone=tz),
            id=jid,
            name=name,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=300,
            kwargs={"job_label": label},
        )
    return scheduler


def registered_job_ids(scheduler: AsyncIOScheduler) -> list[str]:
    return sorted(j.id for j in scheduler.get_jobs())


def health_payload() -> dict:
    """Readiness for Docker healthcheck: DB + expected job IDs in jobstore table."""
    from sqlalchemy import create_engine, text

    from newsroom.storage.database import db_health

    if not db_health():
        return {"status": "unhealthy", "reason": "database"}
    try:
        eng = create_engine(str(settings.database_url), pool_pre_ping=True)
        with eng.connect() as conn:
            rows = conn.execute(text("SELECT id FROM apscheduler_jobs")).fetchall()
        eng.dispose()
        ids = sorted(r[0] for r in rows)
        missing = [j for j in JOB_IDS if j not in ids]
        if missing:
            return {"status": "starting", "jobs": ids, "missing": missing}
        return {"status": "healthy", "jobs": ids}
    except Exception as e:
        return {"status": "unhealthy", "reason": str(e)[:200]}

async def _async_main() -> None:
    setup_logging()
    logger.info("Starting Newsroom scheduler")
    scheduler = create_scheduler()
    scheduler.start()
    logger.info(f"Jobs registered: {registered_job_ids(scheduler)}")
    try:
        with open("/tmp/newsroom_scheduler_ready", "w", encoding="utf-8") as f:
            f.write(json.dumps({"jobs": registered_job_ids(scheduler)}))
    except OSError:
        pass
    try:
        await asyncio.Event().wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
