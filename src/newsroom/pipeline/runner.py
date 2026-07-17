"""Canonical pipeline runner — single async lifecycle, one correlation ID.

All production callers (scheduler, CLI, bot, Hermes cron, PS wrappers) must
invoke run_pipeline() / main(). Nested asyncio.run is forbidden.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from newsroom.logging import get_logger, setup_logging
from newsroom.pipeline.collect import collect_sources
from newsroom.pipeline.lock import PipelineBusyError, PipelineLock
from newsroom.storage.database import engine
from newsroom.storage.models import JobRun, NormalizedItem, RawItem, Report, Story

logger = get_logger(__name__)

EXIT_OK = 0
EXIT_BUSY = 2
EXIT_ERROR = 1


def _correlation_id() -> str:
    env = os.environ.get("NEWSROOM_JOB_ID")
    if env:
        return env
    return f"manual_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _emit(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, ensure_ascii=False, default=str))
    sys.stdout.flush()


async def _deliver(session: Session, report_id: int) -> int | None:
    from newsroom.config import settings
    from newsroom.delivery.telegram import SCHEDULED_CURSOR_KEY, TelegramDelivery

    if not settings.telegram_bot_enabled:
        return None
    td = TelegramDelivery()
    try:
        if not td.client.token:
            return None
        # Scheduled runs advance the delivery cursor on confirmed delivery.
        # Manual runs do not advance the scheduled cursor.
        cursor_key = None
        if os.environ.get("NEWSROOM_SCHEDULE_LABEL"):
            cursor_key = SCHEDULED_CURSOR_KEY
        return await td.deliver_report(session, report_id, cursor_key=cursor_key)
    finally:
        await td.close()


async def _run_async(result: dict[str, Any], session: Session) -> None:
    def stage(name: str, status: str, detail: str = "") -> None:
        entry = {
            "name": name,
            "status": status,
            "detail": detail,
            "ts": datetime.now(UTC).isoformat(),
        }
        result["stages"].append(entry)
        _emit({"stage": name, "status": status, "detail": detail})

    stage("collect", "starting")
    coll = await collect_sources(session)
    session.commit()
    stage("collect", "ok", f"{coll['new_items']} new / {coll['sources']} sources")

    stage("normalize", "starting")
    from newsroom.processing.normalize import Normalizer

    normalizer = Normalizer()
    raw_items = (
        session.query(RawItem)
        .filter(~RawItem.id.in_(session.query(NormalizedItem.raw_item_id)))
        .limit(500)
        .all()
    )
    normalized_count = 0
    for raw in raw_items:
        try:
            norm_data = normalizer.normalize(raw.raw_data)
            session.add(
                NormalizedItem(
                    raw_item_id=raw.id,
                    title=norm_data["title"][:500],
                    description=(norm_data.get("description") or "")[:2000],
                    source_url=norm_data["source_url"],
                    canonical_url=norm_data.get("canonical_url") or "",
                    published_at=norm_data.get("published_at"),
                    language=norm_data.get("language"),
                    content_hash=norm_data["content_hash"],
                    url_hash=norm_data.get("url_hash") or "",
                )
            )
            normalized_count += 1
        except Exception as e:
            stage("normalize", "item_error", f"raw {raw.id}: {str(e)[:80]}")
    session.commit()
    stage("normalize", "ok", f"{normalized_count} items")

    stage("dedupe", "starting")
    from newsroom.processing.dedupe import Deduplicator

    deduper = Deduplicator()
    non_dup = session.query(NormalizedItem).filter(NormalizedItem.is_duplicate.is_(False)).all()
    if non_dup:
        stats = deduper.deduplicate_batch(session, [i.id for i in non_dup])
        session.commit()
        stage("dedupe", "ok", str(stats))
    else:
        stage("dedupe", "ok", "no items")

    stage("cluster", "starting")
    from newsroom.processing.cluster import Clusterer

    clusterer = Clusterer()
    non_dup = session.query(NormalizedItem).filter(NormalizedItem.is_duplicate.is_(False)).all()
    if non_dup:
        cstats = clusterer.cluster_items(session, [i.id for i in non_dup])
        session.commit()
        stage("cluster", "ok", str(cstats))
    else:
        stage("cluster", "ok", "no items")

    stage("evidence", "starting")
    from newsroom.processing.evidence import EvidenceBuilder

    evidence_builder = EvidenceBuilder()
    stories = session.query(Story).order_by(Story.created_at.desc()).limit(30).all()
    if stories:
        estats = evidence_builder.build_for_stories(session, [s.id for s in stories])
        session.commit()
        stage("evidence", "ok", str(estats))
    else:
        stage("evidence", "skipped", "no stories")

    stage("report", "starting")
    story_ids = [s.id for s in stories] if stories else []
    if not story_ids:
        stage("report", "skipped", "no stories")
        result["status"] = "ok_empty"
        return

    # Gate 4: editorial layer (AI when configured, deterministic fallback)
    from newsroom.editorial.orchestrator import generate_editorial

    report_mode = result["report_mode"]
    content, editorial_attempt = generate_editorial(session, story_ids, report_mode)

    report = Report(
        content_fa=content,
        story_ids=story_ids,
        report_mode=report_mode,
        generation_method="ai" if editorial_attempt.provider != "deterministic" else "deterministic",
    )
    session.add(report)
    session.flush()
    result["report_id"] = report.id

    # Persist editorial attempt for audit
    from newsroom.config import settings as _settings
    from newsroom.editorial.persistence import compute_cache_key, persist_attempt

    cache_key = compute_cache_key(
        report_mode,
        editorial_attempt.evidence_set_hash,
        editorial_attempt.prompt_version,
        editorial_attempt.provider,
        editorial_attempt.model,
        temperature=_settings.editorial_temperature,
        max_input_tokens=_settings.editorial_max_input_tokens,
        max_output_tokens=_settings.editorial_max_output_tokens,
    )
    persist_attempt(session, editorial_attempt, report.id, cache_key)

    stage("report", "ok", f"report {report.id} ({editorial_attempt.provider}:{editorial_attempt.status})")

    stage("deliver", "starting")
    delivery_id = await _deliver(session, report.id)
    if delivery_id:
        result["delivery_id"] = delivery_id
        stage("deliver", "ok", f"delivery {delivery_id}")
    else:
        stage("deliver", "skipped", "telegram disabled or not configured")

    result["status"] = "ok"


def run_pipeline(*, blocking_lock: bool = False) -> dict[str, Any]:
    """Run full pipeline under cross-process advisory lock. Sync entrypoint."""
    setup_logging()
    job_id = _correlation_id()
    result: dict[str, Any] = {
        "job_id": job_id,
        "report_mode": os.environ.get("NEWSROOM_REPORT_MODE", "scheduled"),
        "schedule_label": os.environ.get("NEWSROOM_SCHEDULE_LABEL", ""),
        "start_time": datetime.now(UTC).isoformat(),
        "stages": [],
        "status": "running",
        "report_id": None,
        "delivery_id": None,
        "error": None,
        "exit_code": EXIT_OK,
    }

    try:
        with PipelineLock(blocking=blocking_lock) as lock:
            result["lock_owner"] = lock.owner
            session = Session(engine)
            job_run = JobRun(
                job_type="scheduled" if result["schedule_label"] else "manual",
                job_id=job_id,
                trigger="scheduled" if result["schedule_label"] else "manual",
                stage="starting",
                status="running",
                stages_log=[],
            )
            try:
                session.add(job_run)
                session.commit()
                run_pk = job_run.id

                asyncio.run(_run_async(result, session))

                updated = session.get(JobRun, run_pk)
                if updated is not None:
                    updated.status = "ok" if result["status"] in ("ok", "ok_empty") else result["status"]
                    updated.stage = "complete"
                    updated.finished_at = datetime.now(UTC)
                    updated.report_id = result.get("report_id")
                    updated.delivery_id = result.get("delivery_id")
                    updated.stages_log = result["stages"]
                    updated.error_detail = result.get("error")
                    session.commit()
            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)[:500]
                result["exit_code"] = EXIT_ERROR
                try:
                    session.rollback()
                    failed = session.query(JobRun).filter_by(job_id=job_id).first()
                    if failed is not None:
                        failed.status = "error"
                        failed.error_detail = str(e)[:500]
                        failed.finished_at = datetime.now(UTC)
                        failed.stages_log = result["stages"]
                        session.commit()
                except Exception:
                    pass
                _emit({"stage": "pipeline", "status": "error", "detail": str(e)[:200]})
                raise
            finally:
                session.close()
    except PipelineBusyError:
        result["status"] = "busy"
        result["error"] = "pipeline lock held by another process"
        result["exit_code"] = EXIT_BUSY
        result["finish_time"] = datetime.now(UTC).isoformat()
        _emit(result)
        return result
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:500]
        result["exit_code"] = EXIT_ERROR

    result["finish_time"] = datetime.now(UTC).isoformat()
    if result["status"] not in ("ok", "ok_empty", "busy"):
        result["exit_code"] = EXIT_ERROR
    elif result["status"] in ("ok", "ok_empty"):
        result["exit_code"] = EXIT_OK
    _emit(result)
    return result


def main() -> int:
    result = run_pipeline()
    return int(result.get("exit_code", EXIT_ERROR))


if __name__ == "__main__":
    sys.exit(main())
