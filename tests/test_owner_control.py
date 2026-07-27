"""Owner control-plane behavior through its public interface."""

from unittest.mock import MagicMock

import pytest

from newsroom.control import NewsroomControl
from newsroom.storage.models import NewsroomControlSettings, Source


def _control_with_row() -> tuple[NewsroomControl, NewsroomControlSettings, MagicMock]:
    row = NewsroomControlSettings(
        id=1,
        report_language="fa",
        report_source_types=[],
        report_story_count=15,
        schedule_times=["00:00", "06:00", "12:00", "18:00"],
        schedule_enabled=True,
    )
    db = MagicMock()
    db.get.return_value = row
    return NewsroomControl(db), row, db


def test_configure_language_sources_count_and_schedule() -> None:
    control, row, db = _control_with_row()

    result = control.configure(
        language="en",
        source_groups="telegram,github",
        story_count=22,
        schedule_times="01:15, 13:45",
    )

    assert result.report_language == "en"
    assert result.report_source_types == ("github_releases", "telegram")
    assert result.report_story_count == 22
    assert result.schedule_times == ("01:15", "13:45")
    assert row.schedule_enabled is True
    db.flush.assert_called_once()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("language", "de"),
        ("story_count", 0),
        ("story_count", 51),
        ("schedule_times", "25:00"),
        ("source_groups", "unknown"),
    ],
)
def test_configure_rejects_invalid_values(field: str, value: object) -> None:
    control, _, _ = _control_with_row()
    with pytest.raises(ValueError):
        control.configure(**{field: value})


def test_delete_source_is_confirmed_soft_delete() -> None:
    source = Source(id=42, name="Example", type="rss", url="https://example.com/feed")
    source.enabled = True
    source.health_status = "healthy"
    db = MagicMock()
    db.get.return_value = source
    db.query.return_value.filter_by.return_value.all.return_value = []
    control = NewsroomControl(db)

    with pytest.raises(ValueError):
        control.delete_source(42)
    result = control.delete_source(42, confirmed=True)

    assert result.action == "deleted"
    assert source.enabled is False
    assert source.inactive_reason == "owner_deleted"
    assert source.health_status == "unavailable"


def test_import_csv_is_bounded_and_safe_by_default() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter_by.return_value.first.return_value = None
    control = NewsroomControl(db)
    payload = (
        b"name,type,url,language,category\n"
        b"Python Insider,rss,https://blog.python.org/feeds/posts/default,en,programming\n"
        b"Bad Row,unknown,https://example.com,en,programming\n"
    )

    result = control.import_sources("sources.csv", payload)

    assert result.total_rows == 2
    assert result.created == 1
    assert result.skipped == 1
    added = [call.args[0] for call in db.add.call_args_list]
    assert len(added) == 1
    assert added[0].enabled is False
    assert added[0].inactive_reason == "owner_review_required"
