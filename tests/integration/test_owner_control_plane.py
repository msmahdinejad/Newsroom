"""Real PostgreSQL coverage for owner settings and source administration."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from newsroom.control import NewsroomControl
from newsroom.storage.models import Source

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
    source = (
        db.query(Source)
        .filter(Source.url == f"https://example.com/{suffix}.xml")
        .one()
    )
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
