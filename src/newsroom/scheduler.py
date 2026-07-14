"""Persistent scheduler — runs 3 daily Tehran-time report cycles.

Uses APScheduler with Asia/Tehran timezone. Stores job state in PostgreSQL
so it survives restarts. Does NOT depend on conversation memory.
"""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore

from newsroom.config import settings
from newsroom.logging import get_logger, setup_logging

logger = get_logger(__name__)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


async def run_scheduled_pipeline(job_label: str) -> None:
    """Run the full pipeline and deliver. Called by scheduler."""
    logger.info(f"Scheduled job triggered: {job_label}")

    from newsroom.storage.database import get_db
    from newsroom.storage.models import JobRun

    job_id = f"scheduled_{job_label}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    job_run = JobRun(
        job_type="scheduled",
        job_id=job_id,
        trigger="scheduled",
        stage="starting",
        status="running",
        stages_log=[],
    )
    with get_db() as db:
        db.add(job_run)
        db.flush()
        run_id = job_run.id

    try:
        env = {**os.environ, "NEWSROOM_JOB_ID": job_id, "NEWSROOM_SCHEDULE_LABEL": job_label}
        result = subprocess.run(
            [sys.executable, os.path.join(PROJECT_DIR, "scripts", "run_pipeline.py")],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=PROJECT_DIR,
            env=env,
        )

        # Parse result
        status = "ok"
        report_id = None
        error_detail = None
        for line in result.stdout.strip().split("\n"):
            if line.strip().startswith("{") and '"status"' in line:
                try:
                    data = json.loads(line.strip())
                    status = data.get("status", "error")
                    report_id = data.get("report_id")
                    if status == "ok_empty":
                        status = "ok"
                    if data.get("error"):
                        error_detail = data["error"]
                except json.JSONDecodeError:
                    pass

        if result.returncode != 0:
            status = "error"
            error_detail = result.stderr[:500]

        with get_db() as db:
            jr = db.query(JobRun).filter_by(id=run_id).first()
            if jr:
                jr.status = status
                jr.stage = "complete"
                jr.finished_at = datetime.now(timezone.utc)
                jr.report_id = report_id
                jr.error_detail = error_detail
                jr.stages_log = [
                    {"name": "pipeline", "status": status, "ts": datetime.now(timezone.utc).isoformat()}
                ]

        logger.info(f"Job {job_label} finished: {status}")

    except subprocess.TimeoutExpired:
        with get_db() as db:
            jr = db.query(JobRun).filter_by(id=run_id).first()
            if jr:
                jr.status = "error"
                jr.error_detail = "Pipeline timeout (300s)"
                jr.finished_at = datetime.now(timezone.utc)
    except Exception as e:
        logger.error(f"Job {job_label} failed: {e}")
        with get_db() as db:
            jr = db.query(JobRun).filter_by(id=run_id).first()
            if jr:
                jr.status = "error"
                jr.error_detail = str(e)[:500]
                jr.finished_at = datetime.now(timezone.utc)


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the scheduler with Tehran timezone jobs."""
    scheduler = AsyncIOScheduler(timezone="Asia/Tehran")

    # Morning: 09:00 Tehran
    scheduler.add_job(
        run_scheduled_pipeline,
        CronTrigger(hour=9, minute=0, timezone="Asia/Tehran"),
        id="morning_news",
        name="Morning News Report (09:00 Tehran)",
        misfire_grace_time=300,
        max_instances=1,
        kwargs={"job_label": "morning"},
    )

    # Afternoon: 15:00 Tehran
    scheduler.add_job(
        run_scheduled_pipeline,
        CronTrigger(hour=15, minute=0, timezone="Asia/Tehran"),
        id="afternoon_news",
        name="Afternoon News Report (15:00 Tehran)",
        misfire_grace_time=300,
        max_instances=1,
        kwargs={"job_label": "afternoon"},
    )

    # Evening: 21:00 Tehran
    scheduler.add_job(
        run_scheduled_pipeline,
        CronTrigger(hour=21, minute=0, timezone="Asia/Tehran"),
        id="evening_news",
        name="Evening News Report (21:00 Tehran)",
        misfire_grace_time=300,
        max_instances=1,
        kwargs={"job_label": "evening"},
    )

    return scheduler


def main() -> None:
    """Entry point for the scheduler service."""
    setup_logging()
    logger.info("Starting Newsroom scheduler")

    scheduler = create_scheduler()
    scheduler.start()

    try:
        # Keep running
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
