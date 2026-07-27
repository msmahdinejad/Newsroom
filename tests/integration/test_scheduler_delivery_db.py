"""Recovery scheduler/delivery boundary integration checks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from newsroom.pipeline import lock as lock_module
from newsroom.pipeline import runner
from newsroom.storage.models import Delivery, EditorialAttempt, JobRun, Report

pytestmark = pytest.mark.integration


def test_duplicate_scheduled_tick_reuses_completed_boundary(
    db: Session,
    engine,
    database_url: str,
    monkeypatch,
) -> None:
    """The same Tehran boundary has one run, report, and delivery."""
    job_id = "test_gate7_scheduled_20260724_1800"
    stale_runs = db.query(JobRun).filter_by(job_id=job_id).all()
    for stale in stale_runs:
        if stale.delivery_id:
            stale_delivery = db.get(Delivery, stale.delivery_id)
            if stale_delivery is not None:
                db.delete(stale_delivery)
        if stale.report_id:
            stale_report = db.get(Report, stale.report_id)
            if stale_report is not None:
                db.delete(stale_report)
        db.delete(stale)
    db.commit()

    report = Report(
        content_fa="\u06af\u0632\u0627\u0631\u0634 \u0632\u0645\u0627\u0646‌\u0628\u0646\u062f\u06cc‌\u0634\u062f\u0647",
        story_ids=[],
        report_mode="scheduled",
        generation_method="none",
    )
    db.add(report)
    db.flush()
    delivery = Delivery(
        report_id=report.id,
        chat_id="a" * 16,
        chat_ref="chat_test",
        total_chunks=1,
        delivered_chunks=1,
        message_ids=[51001],
        status="delivered",
        attempt_count=1,
        retry_count=0,
        parse_mode="HTML",
    )
    db.add(delivery)
    db.flush()
    db.add(
        JobRun(
            job_type="scheduled",
            job_id=job_id,
            trigger="scheduled",
            stage="complete",
            status="ok",
            report_id=report.id,
            delivery_id=delivery.id,
        )
    )
    db.commit()

    async def unexpected_collection(*args, **kwargs):
        raise AssertionError("a duplicate scheduled tick re-entered the pipeline")

    monkeypatch.setattr(runner, "engine", engine)
    monkeypatch.setattr(lock_module.settings, "database_url", database_url)
    monkeypatch.setattr(runner, "collect_sources", unexpected_collection)
    monkeypatch.setenv("NEWSROOM_JOB_ID", job_id)
    monkeypatch.setenv("NEWSROOM_SCHEDULE_LABEL", "18:00")
    monkeypatch.setenv("NEWSROOM_REPORT_MODE", "scheduled")

    result = runner.run_pipeline()

    assert result["status"] == "ok"
    assert result["deduplicated"] is True
    assert (result["report_id"], result["delivery_id"]) == (
        report.id,
        delivery.id,
    )
    assert db.query(JobRun).filter_by(job_id=job_id).count() == 1
    assert db.query(Report).filter_by(id=report.id).count() == 1

    db.query(JobRun).filter_by(job_id=job_id).delete()
    db.delete(delivery)
    db.delete(report)
    db.commit()


def test_no_news_pipeline_makes_zero_editorial_provider_calls(
    db: Session,
    engine,
    database_url: str,
    monkeypatch,
) -> None:
    """A no-news boundary persists only its notice; it must not enter the LLM."""
    job_id = "test_gate7_no_news_zero_provider_calls"
    db.query(JobRun).filter_by(job_id=job_id).delete()
    db.commit()
    before_attempts = db.query(EditorialAttempt).count()

    async def no_delivery(*_args, **_kwargs):
        return None

    def provider_must_not_run(*_args, **_kwargs):
        raise AssertionError("no-news route called an editorial provider")

    monkeypatch.setattr(runner, "engine", engine)
    monkeypatch.setattr(lock_module.settings, "database_url", database_url)
    monkeypatch.setattr(runner, "_deliver", no_delivery)
    monkeypatch.setattr(
        "newsroom.editorial.selection.select_stories_for_report",
        lambda *_args, **_kwargs: SimpleNamespace(
            story_ids=[],
            no_new_items=True,
            excluded_as_delivered=0,
            total_candidates=0,
            materially_updated=0,
            selected_count=0,
            omitted_count=0,
        ),
    )
    monkeypatch.setattr(
        "newsroom.editorial.orchestrator.generate_editorial", provider_must_not_run
    )
    monkeypatch.setenv("NEWSROOM_JOB_ID", job_id)
    monkeypatch.setenv("NEWSROOM_REPORT_MODE", "scheduled")
    monkeypatch.setenv("NEWSROOM_SCHEDULE_LABEL", "00:00")
    monkeypatch.setenv("NEWSROOM_SKIP_COLLECT", "true")

    result = runner.run_pipeline()

    report = db.get(Report, result["report_id"])
    assert result["status"] == "ok_empty"
    assert report is not None
    assert report.generation_method == "none"
    assert db.query(EditorialAttempt).count() == before_attempts

    db.query(JobRun).filter_by(job_id=job_id).delete()
    db.delete(report)
    db.commit()
