"""Persistent scheduler for independently configured digest definitions.

Jobs re-registered idempotently on startup (replace_existing=True).
Scheduled runs call the same newsroom.pipeline.runner path as manual CLI.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from newsroom.config import settings
from newsroom.logging import get_logger, setup_logging

logger = get_logger(__name__)

# Default preset; every digest may override its timezone and local times.
JOB_IDS = ("report_00", "report_06", "report_12", "report_18")
SCHEDULE_HOURS: tuple[int, ...] = (0, 6, 12, 18)
DEFAULT_SCHEDULE_TIMES = ("00:00", "06:00", "12:00", "18:00")


@dataclass(frozen=True)
class DigestSchedule:
    """Non-secret scheduler projection of one enabled digest."""

    slug: str
    name: str
    timezone: str
    times: tuple[str, ...]


def scheduled_boundary_job_id(
    job_label: str,
    when: datetime | None = None,
    *,
    digest_slug: str = "default",
    timezone: str | None = None,
) -> str:
    """Stable per-digest reporting-window identity used across retries."""
    local_now = when or datetime.now(ZoneInfo(timezone or settings.timezone or "Asia/Tehran"))
    digest_part = "" if digest_slug == "default" else f"_{digest_slug}"
    return f"scheduled{digest_part}_{local_now:%Y%m%d}_{job_label.replace(':', '')}"


def scheduled_specs(
    schedule_times: tuple[str, ...] | list[str] | None = None,
    *,
    digest_slug: str = "default",
    digest_name: str = "Default digest",
    timezone: str | None = None,
) -> list[tuple[str, int, int, str, str]]:
    """Return deterministic cron specs for validated local schedule times."""
    times = DEFAULT_SCHEDULE_TIMES if schedule_times is None else tuple(schedule_times)
    specs: list[tuple[str, int, int, str, str]] = []
    for value in times:
        hour_text, minute_text = value.split(":", maxsplit=1)
        hour, minute = int(hour_text), int(minute_text)
        time_id = f"{hour:02d}" if minute == 0 else f"{hour:02d}{minute:02d}"
        job_id = (
            f"report_{time_id}" if digest_slug == "default" else f"report_{digest_slug}_{time_id}"
        )
        label = f"{hour:02d}:{minute:02d}"
        specs.append(
            (
                job_id,
                hour,
                minute,
                label,
                f"{digest_name} ({label} {timezone or settings.timezone})",
            )
        )
    return specs


async def run_scheduled_pipeline(
    job_label: str,
    digest_slug: str = "default",
    timezone: str | None = None,
) -> None:
    """Invoke authoritative pipeline runner in-process (same lock/path as CLI)."""
    logger.info(
        "Scheduled job triggered: digest=%s boundary=%s",
        digest_slug,
        job_label,
    )
    # A scheduled boundary keeps one durable identity across retries/restarts.
    # This prevents a provider switch or delivery retry from creating another
    # editorial job/report for the same digest-local reporting window.
    from newsroom.pipeline.runner import EXIT_BUSY, PipelineRequest, run_pipeline

    loop = asyncio.get_running_loop()
    request = PipelineRequest(
        job_id=scheduled_boundary_job_id(
            job_label,
            digest_slug=digest_slug,
            timezone=timezone,
        ),
        report_mode="scheduled",
        schedule_label=job_label,
        digest_slug=digest_slug,
    )
    result = await loop.run_in_executor(
        None,
        lambda: run_pipeline(request=request),
    )
    status = result.get("status")
    if status == "busy" or result.get("exit_code") == EXIT_BUSY:
        logger.warning(f"Job {job_label}: pipeline busy (lock held)")
    else:
        logger.info(f"Job {job_label} finished: {status}")


def create_scheduler(
    schedule_times: tuple[str, ...] | list[str] | None = None,
    *,
    digest_schedules: tuple[DigestSchedule, ...] | None = None,
) -> AsyncIOScheduler:
    """Create the scheduler with PostgreSQL persistence and digest-local jobs."""
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

    schedules = (
        (
            DigestSchedule(
                slug="default",
                name="Default digest",
                timezone=settings.timezone or "Asia/Tehran",
                times=(DEFAULT_SCHEDULE_TIMES if schedule_times is None else tuple(schedule_times)),
            ),
        )
        if digest_schedules is None
        else digest_schedules
    )
    _register_digest_jobs(scheduler, schedules)
    _set_schedule_fingerprint(scheduler, schedules)
    return scheduler


def _register_digest_jobs(
    scheduler: AsyncIOScheduler,
    schedules: tuple[DigestSchedule, ...],
) -> None:
    for digest in schedules:
        for jid, hour, minute, label, name in scheduled_specs(
            digest.times,
            digest_slug=digest.slug,
            digest_name=digest.name,
            timezone=digest.timezone,
        ):
            scheduler.add_job(
                run_scheduled_pipeline,
                CronTrigger(
                    hour=hour,
                    minute=minute,
                    timezone=digest.timezone,
                ),
                id=jid,
                name=name,
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=300,
                kwargs={
                    "job_label": label,
                    "digest_slug": digest.slug,
                    "timezone": digest.timezone,
                },
            )


def reconcile_digest_schedules(
    scheduler: AsyncIOScheduler,
    schedules: tuple[DigestSchedule, ...],
) -> bool:
    """Idempotently apply every digest schedule without a service restart."""
    desired_fingerprint = _schedule_fingerprint(schedules)
    desired_ids = {
        spec[0]
        for digest in schedules
        for spec in scheduled_specs(
            digest.times,
            digest_slug=digest.slug,
            digest_name=digest.name,
            timezone=digest.timezone,
        )
    }
    existing_ids = {job.id for job in scheduler.get_jobs() if job.id.startswith("report_")}
    if (
        existing_ids == desired_ids
        and getattr(scheduler, "_newsroom_schedule_fingerprint", None) == desired_fingerprint
    ):
        return False
    # A fingerprint change may retain the same IDs while changing timezone,
    # name, or kwargs. Removing all owned jobs also handles pre-start pending
    # jobs consistently with a running scheduler.
    for job_id in existing_ids:
        scheduler.remove_job(job_id)
    _register_digest_jobs(scheduler, schedules)
    _set_schedule_fingerprint(scheduler, schedules)
    logger.info("Digest schedules updated: %s", sorted(desired_ids))
    return True


def _schedule_fingerprint(
    schedules: tuple[DigestSchedule, ...],
) -> tuple[tuple[str, str, str, tuple[str, ...]], ...]:
    """Stable projection that detects timezone/name changes at unchanged job IDs."""
    return tuple(
        sorted(
            (
                digest.slug,
                digest.name,
                digest.timezone,
                tuple(digest.times),
            )
            for digest in schedules
        )
    )


def _set_schedule_fingerprint(
    scheduler: AsyncIOScheduler,
    schedules: tuple[DigestSchedule, ...],
) -> None:
    scheduler._newsroom_schedule_fingerprint = _schedule_fingerprint(  # type: ignore[attr-defined]
        schedules
    )


def reconcile_schedule(
    scheduler: AsyncIOScheduler,
    schedule_times: tuple[str, ...],
    *,
    enabled: bool = True,
) -> bool:
    """Backward-compatible default-digest schedule adapter."""
    schedules = (
        (
            DigestSchedule(
                slug="default",
                name="Default digest",
                timezone=settings.timezone or "Asia/Tehran",
                times=schedule_times,
            ),
        )
        if enabled
        else ()
    )
    return reconcile_digest_schedules(scheduler, schedules)


def _control_schedule() -> tuple[tuple[str, ...], bool]:
    from newsroom.control import NewsroomControl
    from newsroom.storage.database import get_db

    with get_db() as db:
        snapshot = NewsroomControl(db).settings()
    return snapshot.schedule_times, snapshot.schedule_enabled


def _control_schedules() -> tuple[DigestSchedule, ...]:
    from newsroom.control import DigestCatalog
    from newsroom.storage.database import get_db

    with get_db() as db:
        digests = DigestCatalog(
            db,
            default_timezone=settings.timezone or "Asia/Tehran",
        ).list(enabled=True)
    return tuple(
        DigestSchedule(
            slug=digest.slug,
            name=digest.name,
            timezone=digest.timezone,
            times=digest.schedule_times,
        )
        for digest in digests
        if digest.schedule_enabled
    )


async def _schedule_refresh_loop(scheduler: AsyncIOScheduler) -> None:
    """Poll only non-secret control state; APScheduler remains job owner."""
    while True:
        await asyncio.sleep(30)
        try:
            reconcile_digest_schedules(scheduler, _control_schedules())
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
        schedules = _control_schedules()
        expected = [
            spec[0]
            for digest in schedules
            for spec in scheduled_specs(
                digest.times,
                digest_slug=digest.slug,
                digest_name=digest.name,
                timezone=digest.timezone,
            )
        ]
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
        digest_schedules = _control_schedules()
    except Exception:
        digest_schedules = (
            DigestSchedule(
                slug="default",
                name="Default digest",
                timezone=settings.timezone or "Asia/Tehran",
                times=DEFAULT_SCHEDULE_TIMES,
            ),
        )
    scheduler = create_scheduler(digest_schedules=digest_schedules)
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
