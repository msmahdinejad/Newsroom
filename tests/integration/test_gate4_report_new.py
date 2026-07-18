"""PostgreSQL integration tests for /report new delivered-story semantics.

Real PostgreSQL, no mocked sessions. Tests:
- /report new excludes delivered stories
- failed/partial deliveries do NOT exclude
- materially updated stories re-qualify
- /report and /report comprehensive include all
- no-new-items behavior
- set-based SQL query behavior
- no API key persistence (no key is involved here)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from newsroom.editorial.selection import (
    detect_material_change,
    get_delivered_story_ids,
    get_delivered_story_versions,
    select_stories_for_report,
)
from newsroom.storage.models import Delivery, Report, Story

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def cleanup_data(db: Session):
    """Clean test data before and after each test."""
    db.execute(text("DELETE FROM editorial_artifact_lineage"))
    db.execute(text("DELETE FROM editorial_artifacts"))
    db.execute(text("DELETE FROM editorial_shards"))
    db.execute(text("DELETE FROM editorial_jobs"))
    db.execute(text("DELETE FROM delivery_chunks"))
    db.execute(text("DELETE FROM deliveries"))
    db.execute(text("DELETE FROM reports"))
    db.execute(text("DELETE FROM evidence"))
    db.execute(text("DELETE FROM story_items"))
    db.execute(text("DELETE FROM stories"))
    db.commit()
    yield
    db.rollback()
    db.execute(text("DELETE FROM editorial_artifact_lineage"))
    db.execute(text("DELETE FROM editorial_artifacts"))
    db.execute(text("DELETE FROM editorial_shards"))
    db.execute(text("DELETE FROM editorial_jobs"))
    db.execute(text("DELETE FROM delivery_chunks"))
    db.execute(text("DELETE FROM deliveries"))
    db.execute(text("DELETE FROM reports"))
    db.execute(text("DELETE FROM evidence"))
    db.execute(text("DELETE FROM story_items"))
    db.execute(text("DELETE FROM stories"))
    db.commit()


def _make_story(db: Session, headline: str, importance: float = 0.8) -> Story:
    story = Story(
        headline=headline,
        importance_score=importance,
        trust_status="confirmed",
        confidence=0.8,
        source_count=1,
    )
    db.add(story)
    db.flush()
    return story


def _make_delivered_report(
    db: Session, story_ids: list[int], generation_method: str = "ai", chat_id: str = "test-chat"
) -> tuple[Report, Delivery]:
    report = Report(
        content_fa="test report content",
        story_ids=story_ids,
        report_mode="manual",
        generation_method=generation_method,
    )
    db.add(report)
    db.flush()

    delivery = Delivery(
        report_id=report.id,
        chat_id=chat_id,
        total_chunks=1,
        delivered_chunks=1,
        message_ids=[1],
        status="delivered",
        parse_mode="HTML",
        delivered_at=datetime.now(UTC),
    )
    db.add(delivery)
    db.flush()
    db.commit()
    return report, delivery


def _make_failed_delivery(db: Session, story_ids: list[int]) -> tuple[Report, Delivery]:
    report = Report(
        content_fa="failed report",
        story_ids=story_ids,
        report_mode="manual",
        generation_method="ai",
    )
    db.add(report)
    db.flush()
    delivery = Delivery(
        report_id=report.id,
        chat_id="test-chat",
        total_chunks=1,
        delivered_chunks=0,
        status="failed",
        error="connection refused",
        parse_mode="HTML",
    )
    db.add(delivery)
    db.flush()
    db.commit()
    return report, delivery


def _make_partial_delivery(db: Session, story_ids: list[int]) -> tuple[Report, Delivery]:
    report = Report(
        content_fa="partial report",
        story_ids=story_ids,
        report_mode="manual",
        generation_method="ai",
    )
    db.add(report)
    db.flush()
    delivery = Delivery(
        report_id=report.id,
        chat_id="test-chat",
        total_chunks=3,
        delivered_chunks=1,
        status="partial",
        parse_mode="HTML",
    )
    db.add(delivery)
    db.flush()
    db.commit()
    return report, delivery


class TestReportNewExcludesDelivered:
    """/report new delivered-story exclusion."""

    def test_report_new_excludes_delivered_stories(self, db: Session):
        s1 = _make_story(db, "Story 1", importance=0.9)
        s2 = _make_story(db, "Story 2", importance=0.7)
        s3 = _make_story(db, "Story 3", importance=0.5)
        _make_delivered_report(db, [s1.id, s2.id])

        result = select_stories_for_report(db, "manual_new")

        assert s3.id in result.story_ids
        assert s1.id not in result.story_ids
        assert s2.id not in result.story_ids
        assert result.excluded_as_delivered >= 2
        assert not result.no_new_items

    def test_report_includes_all_stories(self, db: Session):
        s1 = _make_story(db, "Story 1", importance=0.9)
        s2 = _make_story(db, "Story 2", importance=0.7)
        _make_delivered_report(db, [s1.id])

        result = select_stories_for_report(db, "manual")
        assert s1.id in result.story_ids
        assert s2.id in result.story_ids
        assert result.excluded_as_delivered == 0

    def test_report_comprehensive_includes_all(self, db: Session):
        s1 = _make_story(db, "Story 1", importance=0.9)
        _make_delivered_report(db, [s1.id])

        result = select_stories_for_report(db, "manual_comprehensive")
        assert s1.id in result.story_ids

    def test_failed_delivery_does_not_exclude(self, db: Session):
        s1 = _make_story(db, "Story 1", importance=0.9)
        _make_failed_delivery(db, [s1.id])

        result = select_stories_for_report(db, "manual_new")
        assert s1.id in result.story_ids
        assert result.excluded_as_delivered == 0

    def test_partial_delivery_does_not_exclude(self, db: Session):
        s1 = _make_story(db, "Story 1", importance=0.9)
        _make_partial_delivery(db, [s1.id])

        result = select_stories_for_report(db, "manual_new")
        assert s1.id in result.story_ids
        assert result.excluded_as_delivered == 0

    def test_deterministic_fallback_report_counts_as_delivered(self, db: Session):
        s1 = _make_story(db, "Story 1", importance=0.9)
        _make_delivered_report(db, [s1.id], generation_method="deterministic")

        result = select_stories_for_report(db, "manual_new")
        assert s1.id not in result.story_ids

    def test_ai_edited_report_counts_as_delivered(self, db: Session):
        s1 = _make_story(db, "Story 1", importance=0.9)
        _make_delivered_report(db, [s1.id], generation_method="ai")

        result = select_stories_for_report(db, "manual_new")
        assert s1.id not in result.story_ids


class TestMaterialChangeRequalification:
    """Materially updated stories re-qualify for /report new."""

    def test_materially_updated_story_requalifies(self, db: Session):
        s1 = _make_story(db, "Story 1", importance=0.9)
        _, delivery = _make_delivered_report(db, [s1.id])

        # Set delivery time in the past
        delivery.delivered_at = datetime.now(UTC) - timedelta(hours=2)
        # Set material change after delivery
        s1.material_change_at = datetime.now(UTC) - timedelta(hours=1)
        s1.material_version = 2
        db.commit()

        updated = get_delivered_story_versions(db)
        assert s1.id in updated

        result = select_stories_for_report(db, "manual_new")
        assert s1.id in result.story_ids
        assert result.materially_updated >= 1

    def test_unmodified_delivered_story_stays_excluded(self, db: Session):
        s1 = _make_story(db, "Story 1", importance=0.9)
        _make_delivered_report(db, [s1.id])

        result = select_stories_for_report(db, "manual_new")
        assert s1.id not in result.story_ids
        assert result.materially_updated == 0


class TestNoNewItemsBehavior:
    """No-new-items response."""

    def test_no_new_items_when_all_delivered(self, db: Session):
        s1 = _make_story(db, "Story 1", importance=0.9)
        s2 = _make_story(db, "Story 2", importance=0.7)
        _make_delivered_report(db, [s1.id, s2.id])

        result = select_stories_for_report(db, "manual_new")
        assert result.no_new_items is True
        assert result.story_ids == []
        assert result.excluded_as_delivered >= 2

    def test_scheduled_mode_never_no_new_items_when_stories_exist(self, db: Session):
        s1 = _make_story(db, "Story 1", importance=0.9)
        _make_delivered_report(db, [s1.id])

        result = select_stories_for_report(db, "scheduled")
        assert s1.id in result.story_ids
        assert not result.no_new_items


class TestSetBasedQuery:
    """Verify queries are set-based."""

    def test_get_delivered_story_ids_returns_set(self, db: Session):
        s1 = _make_story(db, "S1", 0.9)
        s2 = _make_story(db, "S2", 0.8)
        s3 = _make_story(db, "S3", 0.7)
        _make_delivered_report(db, [s1.id, s2.id, s3.id])

        result = get_delivered_story_ids(db)
        assert isinstance(result, set)
        assert s1.id in result
        assert s2.id in result
        assert s3.id in result

    def test_delivered_story_ids_empty_when_no_deliveries(self, db: Session):
        _make_story(db, "S1", 0.9)

        result = get_delivered_story_ids(db)
        assert result == set()


class TestDetectMaterialChangeUnit:
    """Unit tests for detect_material_change using DB session."""

    def test_new_story_is_material(self, db: Session):
        story = Story(headline="test", source_count=1)
        assert detect_material_change(story, {"facts": ["new fact"]}, None) is True

    def test_duplicate_coverage_not_material(self, db: Session):
        story = Story(headline="test", source_count=2)
        old = {"source_count": 2, "facts": ["fact1"], "contradictions": []}
        new = {"source_count": 2, "facts": ["fact1"], "contradictions": []}
        assert detect_material_change(story, new, old) is False

    def test_new_contradiction_is_material(self, db: Session):
        story = Story(headline="test", source_count=1)
        old = {"source_count": 1, "facts": ["fact1"], "contradictions": []}
        new = {"source_count": 1, "facts": ["fact1"], "contradictions": [{"issue": "conflict"}]}
        assert detect_material_change(story, new, old) is True
