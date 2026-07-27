"""Persistent scheduler — APScheduler + SQLAlchemy job store, Asia/Tehran.

Jobs re-registered idempotently on startup (replace_existing=True).
Scheduled runs call the same newsroom.pipeline.runner path as manual CLI.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from newsroom.config import settings
from newsroom.logging import get_logger, setup_logging

logger = get_logger(__name__)

# 00:00, 06:00, 12:00, 18:00 — independent of host/container timezone.
JOB_IDS = ("report_00", "report_06", "report_12", "report_18")
SCHEDULE_HOURS: tuple[int, ...] = (0, 6, 12, 18)
DEFAULT_SCHEDULE_TIMES = ("00:00", "06:00", "12:00", "18:00")


def scheduled_boundary_job_id(job_label: str, when: datetime | None = None) -> str:
    """Stable Tehran reporting-window identity used across retries."""
    tehran_now = when or datetime.now(ZoneInfo(settings.timezone or "Asia/Tehran"))
    return f"scheduled_{tehran_now:%Y%m%d}_{job_label.replace(':', '')}"


def scheduled_specs(
    schedule_times: tuple[str, ...] | list[str] | None = None,
) -> list[tuple[str, int, int, str, str]]:
    """Return deterministic cron specs for validated Tehran schedule times."""
    times = (
        DEFAULT_SCHEDULE_TIMES
        if schedule_times is None
        else tuple(schedule_times)
    )
    specs: list[tuple[str, int, int, str, str]] = []
    for value in times:
        hour_text, minute_text = value.split(":", maxsplit=1)
        hour, minute = int(hour_text), int(minute_text)
        job_id = f"report_{hour:02d}" if minute == 0 else f"report_{hour:02d}{minute:02d}"
        label = f"{hour:02d}:{minute:02d}"
        specs.append(
            (job_id, hour, minute, label, f"Scheduled report ({label} Tehran)")
        )
    return specs


async def run_scheduled_pipeline(job_label: str) -> None:
    """Invoke authoritative pipeline runner in-process (same lock/path as CLI)."""
    logger.info(f"Scheduled job triggered: {job_label}")
    # A scheduled boundary keeps one durable identity across retries/restarts.
    # This prevents a provider switch or delivery retry from creating another
    # editorial job/report for the same Tehran reporting window.
    os.environ["NEWSROOM_JOB_ID"] = scheduled_boundary_job_id(job_label)
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


def create_scheduler(
    schedule_times: tuple[str, ...] | list[str] | None = None,
) -> AsyncIOScheduler:
    """Create scheduler with PostgreSQL job store and current Tehran cron jobs."""
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
    for jid, hour, minute, label, name in scheduled_specs(schedule_times):
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


def reconcile_schedule(
    scheduler: AsyncIOScheduler,
    schedule_times: tuple[str, ...],
    *,
    enabled: bool = True,
) -> bool:
    """Idempotently apply owner schedule changes without restarting services."""
    desired_specs = scheduled_specs(schedule_times) if enabled else []
    desired_ids = {spec[0] for spec in desired_specs}
    existing_ids = {
        job.id for job in scheduler.get_jobs() if job.id.startswith("report_")
    }
    if existing_ids == desired_ids:
        return False
    for job_id in existing_ids - desired_ids:
        scheduler.remove_job(job_id)
    tz = settings.timezone or "Asia/Tehran"
    for jid, hour, minute, label, name in desired_specs:
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
    logger.info("Owner schedule updated: %s", sorted(desired_ids))
    return True


def _control_schedule() -> tuple[tuple[str, ...], bool]:
    from newsroom.control import NewsroomControl
    from newsroom.storage.database import get_db

    with get_db() as db:
        snapshot = NewsroomControl(db).settings()
    return snapshot.schedule_times, snapshot.schedule_enabled


async def _schedule_refresh_loop(scheduler: AsyncIOScheduler) -> None:
    """Poll only non-secret control state; APScheduler remains job owner."""
    while True:
        await asyncio.sleep(30)
        try:
            schedule_times, enabled = _control_schedule()
            reconcile_schedule(scheduler, schedule_times, enabled=enabled)
        except Exception as exc:
            logger.warning(
                "Schedule refresh failed (%s); retaining last valid schedule",
                type(exc).__name__,
            )


def registered_job_ids(scheduler: AsyncIOScheduler) -> list[str]:
    return sorted(j.id for j in scheduler.get_jobs())


def health_payload() -> dict:
    """Readiness for Docker healthcheck: DB + configured job IDs."""
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
        schedule_times, enabled = _control_schedule()
        expected = [spec[0] for spec in scheduled_specs(schedule_times)] if enabled else []
        missing = [job_id for job_id in expected if job_id not in ids]
        if missing:
            return {"status": "starting", "jobs": ids, "missing": missing}
        return {"status": "healthy", "jobs": ids}
    except Exception as e:
        return {"status": "unhealthy", "reason": str(e)[:200]}

async def _async_main() -> None:
    setup_logging()
    logger.info("Starting Newsroom scheduler")
    try:
        schedule_times, enabled = _control_schedule()
    except Exception:
        schedule_times, enabled = DEFAULT_SCHEDULE_TIMES, True
    scheduler = create_scheduler(schedule_times if enabled else ())
    scheduler.start()
    refresh_task = asyncio.create_task(_schedule_refresh_loop(scheduler))
    logger.info(f"Jobs registered: {registered_job_ids(scheduler)}")
    try:
        with open("/tmp/newsroom_scheduler_ready", "w", encoding="utf-8") as f:
            f.write(json.dumps({"jobs": registered_job_ids(scheduler)}))
    except OSError:
        pass
    try:
        await asyncio.Event().wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await refresh_task
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
