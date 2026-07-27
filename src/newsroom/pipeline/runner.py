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
from newsroom.storage.models import Delivery, JobRun, Report

logger = get_logger(__name__)

EXIT_OK = 0
EXIT_BUSY = 2
EXIT_ERROR = 1


def generation_method_for_attempt(attempt: Any) -> str:
    """Truthful report label: any deterministic fallback is not an AI success."""
    used_ai = (
        attempt.provider != "deterministic"
        and attempt.status == "ok"
        and not attempt.fallback_used
    )
    return "ai" if used_ai else "deterministic"


def delivery_allowed_for_attempt(attempt: Any) -> bool:
    """Only validated AI copy may cross the public delivery boundary."""
    return generation_method_for_attempt(attempt) == "ai"


def report_story_ids_for_attempt(selected_story_ids: list[int], attempt: Any) -> list[int]:
    """Persist only stories actually present in the validated final output."""
    output = getattr(attempt, "output", None)
    output_stories = getattr(output, "stories", None)
    if not output_stories:
        return selected_story_ids
    selected = set(selected_story_ids)
    return list(dict.fromkeys(story.story_id for story in output_stories if story.story_id in selected))


def _correlation_id() -> str:
    env = os.environ.get("NEWSROOM_JOB_ID")
    if env:
        return env
    return f"manual_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _emit(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, ensure_ascii=False, default=str))
    sys.stdout.flush()


def _collection_kwargs() -> dict[str, Any]:
    """Bound scheduled native collection and keep dedicated owners exclusive."""
    from newsroom.config import settings

    return {
        "limit_per_source": settings.collect_limit_per_source,
        "max_sources": settings.collect_max_sources_per_cycle,
        "source_spacing_seconds": settings.collect_source_spacing_seconds,
        "exclude_source_types": {"telegram", "x_timeline"},
    }


def _agent_reach_collection_kwargs() -> dict[str, Any]:
    """Bound optional Agent-Reach work to the same fair cycle budget."""
    from newsroom.config import settings

    return {
        "limit_per_source": settings.collect_limit_per_source,
        "max_sources": settings.collect_max_sources_per_cycle,
        "min_source_spacing_seconds": settings.collect_source_spacing_seconds,
    }


def _completed_scheduled_run(
    session: Session,
    job_id: str,
    schedule_label: str,
) -> JobRun | None:
    """Return a fully delivered run for the same durable Tehran boundary."""
    if not schedule_label:
        return None
    existing = (
        session.query(JobRun)
        .filter_by(job_id=job_id, trigger="scheduled")
        .order_by(JobRun.id.desc())
        .first()
    )
    if (
        existing is None
        or existing.status != "ok"
        or existing.report_id is None
        or existing.delivery_id is None
    ):
        return None
    delivery = session.get(Delivery, existing.delivery_id)
    if delivery is None or delivery.status != "delivered":
        return None
    return existing


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
        delivery_id = await td.deliver_report(session, report_id, cursor_key=cursor_key)
        if delivery_id is None:
            return None

        # ``deliver_report`` returns an ID for partial delivery so the same
        # record can be resumed.  A pipeline boundary is successful only when
        # every chunk is confirmed delivered; partial state must never be
        # reported as success or advance the schedule.
        from newsroom.storage.models import Delivery

        delivery = session.get(Delivery, delivery_id)
        if delivery is None or delivery.status != "delivered":
            raise RuntimeError(f"telegram delivery {delivery_id} incomplete")
        return delivery_id
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

    skip_collect = os.environ.get("NEWSROOM_SKIP_COLLECT", "").lower() in ("1", "true", "yes", "on")

    if skip_collect:
        stage("collect", "skipped", "NEWSROOM_SKIP_COLLECT set")
    else:
        stage("collect", "starting")
        coll = await collect_sources(session, **_collection_kwargs())
        session.commit()
        stage("collect", "ok", f"{coll['new_items']} new / {coll['sources']} sources")

    # Social collection: Agent-Reach-backed external sources (YouTube, web, etc.).
    # Skipped cleanly when Agent-Reach is disabled or no AR sources configured.
    from newsroom.pipeline.social_collect import collect_agent_reach_sources

    if skip_collect:
        stage("collect_agent_reach", "skipped", "NEWSROOM_SKIP_COLLECT set")
    else:
        stage("collect_agent_reach", "starting")
        ar_coll = await collect_agent_reach_sources(
            session,
            **_agent_reach_collection_kwargs(),
        )
        session.commit()
        if ar_coll.get("disabled"):
            stage("collect_agent_reach", "skipped", "agent_reach_disabled")
        elif ar_coll["sources"] == 0:
            stage("collect_agent_reach", "skipped", "no agent_reach sources")
        else:
            stage(
                "collect_agent_reach",
                "ok",
                f"{ar_coll['new_items']} new / {ar_coll['sources']} sources",
            )

    stage("normalize", "starting")
    from newsroom.pipeline.processing_worker import process_pending_items

    processed = process_pending_items(batch_size=500)
    stage(
        "normalize",
        "ok",
        f"{processed.normalized} normalized / {processed.raw_seen} claimed",
    )

    stage("dedupe", "starting")
    stage("dedupe", "ok", f"{processed.duplicates} duplicates in claimed batch")

    stage("cluster", "starting")
    stage("cluster", "ok", f"{processed.clustered} items clustered in claimed batch")

    stage("report", "starting")
    from newsroom.control import NewsroomControl
    from newsroom.editorial.report_profiles import resolve_report_profile
    from newsroom.editorial.selection import select_stories_for_report

    report_mode = result["report_mode"]
    report_profile = resolve_report_profile(report_mode)
    control = NewsroomControl(session).settings()
    uses_owner_defaults = report_mode in {
        "scheduled",
        "manual",
        "manual_new",
        "manual_comprehensive",
    }
    report_story_count = (
        control.report_story_count if uses_owner_defaults else report_profile.max_stories
    )
    selected_source_types = (
        control.report_source_types if uses_owner_defaults else None
    )
    report_language = control.report_language
    selection = select_stories_for_report(
        session,
        report_mode,
        max_stories=report_story_count,
        source_types=selected_source_types,
    )
    story_ids = selection.story_ids

    stage("evidence", "starting")
    if story_ids:
        from newsroom.processing.evidence import EvidenceBuilder

        estats = EvidenceBuilder().build_for_stories(session, story_ids)
        session.commit()
        stage("evidence", "ok", str(estats))
    else:
        stage("evidence", "skipped", "no selected stories")

    if not story_ids or selection.no_new_items:
        stage("report", "skipped", f"no new items (excluded {selection.excluded_as_delivered} delivered)")
        result["status"] = "ok_empty"
        result["no_new_items"] = True
        result["selection_stats"] = {
            "total_candidates": selection.total_candidates,
            "excluded_as_delivered": selection.excluded_as_delivered,
            "materially_updated": selection.materially_updated,
            "selected": selection.selected_count,
            "omitted": selection.omitted_count,
        }
        # No-news path: persist a short Persian notice, deliver it, and advance
        # the scheduled cursor — with ZERO editorial provider calls.
        from newsroom.editorial.orchestrator import _empty_report

        notice = _empty_report(report_mode, report_language)
        report = Report(
            content_fa=notice,
            story_ids=[],
            report_mode=report_mode,
            generation_method="none",
        )
        session.add(report)
        session.flush()
        result["report_id"] = report.id
        result["no_news_notice"] = True
        stage("report", "ok", f"no-news notice {report.id} (zero provider calls)")
        stage("deliver", "starting")
        delivery_id = await _deliver(session, report.id)
        if delivery_id:
            result["delivery_id"] = delivery_id
            stage("deliver", "ok", f"no-news notice delivery {delivery_id}")
        else:
            stage("deliver", "skipped", "telegram disabled or not configured")
        return

    # Editorial: editorial layer — hierarchical for large sets, single-call for small
    from newsroom.config import settings as _cfg
    from newsroom.editorial.orchestrator import generate_editorial

    if len(story_ids) > _cfg.editorial_max_stories_per_call:
        from newsroom.editorial.hierarchy import run_hierarchical_editorial

        hier_result = run_hierarchical_editorial(
            session,
            story_ids,
            report_mode,
            job_id=result["job_id"],
            report_language=report_language,
        )
        content = hier_result.content
        editorial_attempt = hier_result.attempt
        result["hierarchical"] = True
        result["shard_count"] = hier_result.job.shard_count
        result["total_model_calls"] = hier_result.total_model_calls
        result["total_input_tokens"] = hier_result.total_input_tokens
        result["total_output_tokens"] = hier_result.total_output_tokens
        result["cache_hits"] = hier_result.cache_hits
        result["fallback_shards"] = hier_result.fallback_shards
    else:
        content, editorial_attempt = generate_editorial(
            session,
            story_ids,
            report_mode,
            job_id=result["job_id"],
            report_language=report_language,
        )

    existing_report_id = (
        hier_result.job.report_id if result.get("hierarchical") and hier_result.job else None
    )
    resumed_report = session.get(Report, existing_report_id) if existing_report_id else None
    report_reused = resumed_report is not None
    if resumed_report is None:
        resumed_report = Report(
            content_fa=content,
            story_ids=report_story_ids_for_attempt(story_ids, editorial_attempt),
            report_mode=report_mode,
            generation_method=generation_method_for_attempt(editorial_attempt),
        )
        session.add(resumed_report)
        session.flush()
        if result.get("hierarchical"):
            hier_result.job.report_id = resumed_report.id
            session.flush()
    report = resumed_report
    result["report_id"] = report.id

    # Reconcile independently committed provider-route events to the report
    # created at the durable editorial boundary. No prompt, response, or
    # provider access value is copied into the lineage table.
    from newsroom.storage.models import ProviderRouteAttempt

    session.query(ProviderRouteAttempt).filter(
        ProviderRouteAttempt.editorial_job_id == result["job_id"],
        ProviderRouteAttempt.report_id.is_(None),
    ).update({ProviderRouteAttempt.report_id: report.id}, synchronize_session=False)

    # Persist editorial attempt for audit
    from newsroom.config import settings as _settings
    from newsroom.editorial.persistence import (
        cache_route_identity,
        compute_cache_key,
        persist_attempt,
    )

    cache_provider, cache_model = cache_route_identity(
        editorial_attempt.provider,
        editorial_attempt.model,
    )

    cache_key: str | None = compute_cache_key(
        report_mode,
        editorial_attempt.evidence_set_hash,
        editorial_attempt.prompt_version,
        cache_provider,
        cache_model,
        temperature=_settings.editorial_temperature,
        max_input_tokens=_settings.editorial_max_input_tokens,
        max_output_tokens=_settings.editorial_max_output_tokens,
    )
    # Failed/terminal-fallback attempts are audit events, not reusable cache
    # artifacts. PostgreSQL therefore permits subsequent bounded retries.
    if editorial_attempt.fallback_used:
        cache_key = None
    from newsroom.storage.models import EditorialAttempt as EditorialAttemptModel

    existing_attempt = (
        session.query(EditorialAttemptModel).filter_by(report_id=report.id).first()
        if report_reused
        else None
    )
    if existing_attempt is None:
        persist_attempt(session, editorial_attempt, report.id, cache_key)

    stage("report", "ok", f"report {report.id} ({editorial_attempt.provider}:{editorial_attempt.status})")
    result["selection_stats"] = {
        "total_candidates": selection.total_candidates,
        "excluded_as_delivered": selection.excluded_as_delivered,
        "materially_updated": selection.materially_updated,
        "selected": selection.selected_count,
        "omitted": selection.omitted_count,
    }

    if not delivery_allowed_for_attempt(editorial_attempt):
        result["status"] = "ai_unavailable"
        result["error"] = "validated AI editorial unavailable; fallback retained for audit"
        stage("deliver", "skipped", "deterministic fallback is not public copy")
        return

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
            completed = _completed_scheduled_run(
                session,
                job_id,
                result["schedule_label"],
            )
            if completed is not None:
                result["status"] = "ok"
                result["report_id"] = completed.report_id
                result["delivery_id"] = completed.delivery_id
                result["deduplicated"] = True
                result["finish_time"] = datetime.now(UTC).isoformat()
                session.close()
                _emit(result)
                return result
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
