"""Named digest domain behavior through its public interface."""

from unittest.mock import MagicMock

import pytest

from newsroom.control import DigestCatalog, DigestUpdate
from newsroom.sources.platforms import (
    USER_SOURCE_TYPES,
    expand_platforms,
    normalize_user_source_type,
)
from newsroom.storage.models import DigestDefinition, NewsroomControlSettings


def _digest() -> DigestDefinition:
    return DigestDefinition(
        id=7,
        slug="default",
        name="My briefing",
        topic_brief="Climate policy and renewable energy markets.",
        include_terms=["solar"],
        exclude_terms=["celebrity"],
        output_language="en",
        timezone="Europe/Berlin",
        source_types=["telegram", "rss"],
        max_stories=12,
        minimum_telegram_stories=2,
        schedule_times=["08:00", "17:30"],
        schedule_enabled=True,
        enabled=True,
        provider_policy={},
        delivery_config={},
    )


def test_digest_snapshot_is_topic_agnostic() -> None:
    row = _digest()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = row

    result = DigestCatalog(db).get()

    assert result.interest.topic_brief.startswith("Climate policy")
    assert result.interest.include_terms == ("solar",)
    assert result.output_language == "en"
    assert result.timezone == "Europe/Berlin"
    assert result.minimum_telegram_stories == 2


def test_digest_update_validates_policy_and_projects_legacy_settings() -> None:
    row = _digest()
    legacy = NewsroomControlSettings(id=1)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = row
    db.get.return_value = legacy

    result = DigestCatalog(db).update(
        "default",
        DigestUpdate(
            topic_brief="Independent cinema releases and film festivals.",
            include_terms=("documentary", "festival", "festival"),
            output_language="fa",
            timezone="Asia/Tehran",
            source_groups=("telegram", "reddit"),
            max_stories=20,
            schedule_times=("09:00", "21:00"),
        ),
    )

    assert result.interest.include_terms == ("documentary", "festival")
    assert result.source_types == ("reddit_subreddit", "telegram")
    assert legacy.report_language == "fa"
    assert legacy.report_story_count == 20
    assert legacy.schedule_times == ["09:00", "21:00"]


@pytest.mark.parametrize(
    "change",
    [
        DigestUpdate(timezone="Mars/Olympus"),
        DigestUpdate(topic_brief="short"),
        DigestUpdate(max_stories=0),
        DigestUpdate(provider_policy={"api_key": "must-not-be-stored"}),
        DigestUpdate(minimum_telegram_stories=13),
    ],
)
def test_digest_update_rejects_invalid_or_secret_configuration(
    change: DigestUpdate,
) -> None:
    row = _digest()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = row

    with pytest.raises(ValueError):
        DigestCatalog(db).update("default", change)


def test_source_platform_registry_is_closed_to_user_defined_types() -> None:
    assert {
        "telegram",
        "x_timeline",
        "reddit_subreddit",
        "github_releases",
        "rss",
        "web_page",
    } == USER_SOURCE_TYPES
    assert expand_platforms(["web"]) == ("rss", "web_page")
    assert normalize_user_source_type("telegram") == "telegram"
    with pytest.raises(ValueError):
        normalize_user_source_type("youtube_rss")
    with pytest.raises(ValueError):
        normalize_user_source_type("custom_python_adapter")
