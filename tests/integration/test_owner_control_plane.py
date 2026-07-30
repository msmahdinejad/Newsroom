"""Real PostgreSQL coverage for owner settings and source administration."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from newsroom.control import DigestCatalog, DigestUpdate, NewsroomControl
from newsroom.storage.models import DigestDefinition, JobRun, Report, Source

pytestmark = pytest.mark.integration


def test_control_preferences_round_trip_in_postgresql(db: Session) -> None:
    control = NewsroomControl(db)
    original = control.settings()

    changed = control.configure(
        language="en",
        source_groups="telegram,github",
        story_count=21,
        schedule_times="01:15,13:45",
    )
    db.flush()
    db.expire_all()
    restored = NewsroomControl(db).settings()

    assert restored == changed
    assert restored.report_source_types == ("github_releases", "telegram")
    # Restore inside the test transaction so fixture rollback is not relied on
    # for the assertion and production defaults remain explicit.
    control.configure(
        language=original.report_language,
        source_groups=list(original.report_source_types) or "all",
        story_count=original.report_story_count,
        schedule_times=list(original.schedule_times),
        schedule_enabled=original.schedule_enabled,
    )


def test_import_enable_disable_and_archive_preserve_source_row(db: Session) -> None:
    suffix = uuid4().hex
    payload = (
        "name,type,url,language,category,enabled\n"
        f"Control Test {suffix},rss,https://example.com/{suffix}.xml,en,programming,false\n"
    ).encode()
    control = NewsroomControl(db)

    imported = control.import_sources("sources.csv", payload)
    db.flush()
    source = db.query(Source).filter(Source.url == f"https://example.com/{suffix}.xml").one()
    assert imported.created == 1
    assert source.enabled is False

    control.set_source_enabled(source.id, True)
    assert source.enabled is True
    control.set_source_enabled(source.id, False)
    assert source.inactive_reason == "owner_disabled"
    control.delete_source(source.id, confirmed=True)

    assert db.get(Source, source.id) is source
    assert source.enabled is False
    assert source.inactive_reason == "owner_deleted"


def test_named_digest_and_report_lineage_round_trip(db: Session) -> None:
    suffix = uuid4().hex[:10]
    control = NewsroomControl(db)
    source_result = control.add_source(
        name=f"Climate source {suffix}",
        source_type="rss",
        url=f"https://example.com/{suffix}/feed.xml",
        enabled=True,
    )
    catalog = DigestCatalog(db)
    created = catalog.create(
        slug=f"climate-{suffix}",
        name="Climate briefing",
        topic_brief="Climate policy, renewable energy, and grid storage markets.",
        output_language="en",
        timezone="Europe/Berlin",
    )
    updated = catalog.update(
        created.slug,
        DigestUpdate(
            source_groups=("web",),
            source_ids=(source_result.source_id,),
            max_stories=19,
            minimum_telegram_stories=0,
            schedule_times=("08:00", "17:30"),
        ),
    )
    digest_row = db.query(DigestDefinition).filter(DigestDefinition.slug == created.slug).one()
    report = Report(
        content_fa="Climate briefing",
        story_ids=[],
        report_mode="manual",
        generation_method="ai",
        digest_id=digest_row.id,
        digest_slug=digest_row.slug,
    )
    db.add(report)
    db.flush()
    run = JobRun(
        job_type="manual",
        job_id=f"manual-{suffix}",
        trigger="manual",
        digest_id=digest_row.id,
        digest_slug=digest_row.slug,
        report_id=report.id,
        status="ok",
    )
    db.add(run)
    db.flush()
    db.expire_all()

    restored = catalog.get(created.slug)
    stored_report = db.get(Report, report.id)
    stored_run = db.get(JobRun, run.id)

    assert restored == updated
    assert restored.source_ids == (source_result.source_id,)
    assert restored.schedule_times == ("08:00", "17:30")
    assert stored_report is not None
    assert stored_report.digest_slug == created.slug
    assert stored_run is not None
    assert stored_run.digest_id == digest_row.id
