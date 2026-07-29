"""Report profiles, generic interests, and platform-only digests."""

from __future__ import annotations

import pytest

from newsroom.control import InterestPolicy
from newsroom.editorial.report_profiles import (
    is_interest_material,
    is_programming_material,
    is_usable_editorial_material,
    resolve_report_profile,
)


def test_default_report_profile_is_subject_neutral():
    profile = resolve_report_profile("scheduled")

    assert profile.source_types is None
    assert profile.minimum_telegram_stories == 2
    assert profile.title_en == "News digest"
    assert "\u062e\u0628\u0631\u0646\u0627\u0645\u0647" in profile.title_fa


@pytest.mark.parametrize(
    ("mode", "source_types"),
    [
        ("platform_telegram", frozenset({"telegram"})),
        ("platform_x", frozenset({"x_timeline"})),
        ("platform_web", frozenset({"web_page", "rss"})),
        ("platform_github", frozenset({"github_releases"})),
        ("platform_reddit", frozenset({"reddit_subreddit"})),
    ],
)
def test_platform_profiles_are_exclusive_and_comprehensive(mode, source_types):
    profile = resolve_report_profile(mode)

    assert profile.source_types == source_types
    assert profile.comprehensive is True
    assert profile.max_stories > resolve_report_profile("scheduled").max_stories


def test_interest_filter_supports_an_unrelated_user_topic() -> None:
    interest = InterestPolicy(
        topic_brief="Climate policy, renewable energy and carbon markets.",
        include_terms=("solar power",),
        exclude_terms=("celebrity",),
    )

    assert is_interest_material(
        interest=interest,
        category="Energy",
        title="New solar power capacity reaches the national grid",
        description="Renewable energy investment increased this quarter.",
        source_type="rss",
    )
    assert not is_interest_material(
        interest=interest,
        category="Entertainment",
        title="Celebrity interview dominates weekend television",
        description="",
        source_type="rss",
    )


@pytest.mark.parametrize(
    ("category", "title", "description", "source_type"),
    [
        ("APIs & Developer Tools", "Free APIs for AI applications", "", "telegram"),
        (
            "Programming",
            "\u06a9\u062a\u0627\u0628\u062e\u0627\u0646\u0647 \u062c\u062f\u06cc\u062f \u067e\u0627\u06cc\u062a\u0648\u0646 \u0628\u0631\u0627\u06cc \u0633\u0627\u062e\u062a API",
            "",
            "telegram",
        ),
        ("Tech News", "New open-source SDK and CLI released", "", "web_page"),
        ("Community", "How to fix a Node.js memory leak in production", "", "reddit_subreddit"),
        ("Open Source", "v2.0 release adds a Rust client library", "", "github_releases"),
    ],
)
def test_programming_filter_keeps_tools_projects_models_and_free_apis(
    category,
    title,
    description,
    source_type,
):
    assert is_programming_material(
        category=category,
        title=title,
        description=description,
        source_type=source_type,
    )


@pytest.mark.parametrize(
    ("category", "title"),
    [
        (
            "Sports",
            "\u062a\u0627\u0631\u06cc\u062e\u0686\u0647 \u06a9\u0627\u0631\u062a \u0642\u0631\u0645\u0632 \u062f\u0631 \u0641\u0648\u062a\u0628\u0627\u0644",
        ),
        (
            "Health",
            "\u0646\u062d\u0648\u0647 \u0627\u062b\u0631 \u062f\u0627\u0631\u0648\u06cc \u0644\u0627\u063a\u0631\u06cc \u0628\u0631 \u0628\u062f\u0646",
        ),
        (
            "Digital Culture",
            "\u062a\u06cc\u0632\u0631 \u0633\u0631\u06cc\u0627\u0644 \u062c\u062f\u06cc\u062f \u0645\u0646\u062a\u0634\u0631 \u0634\u062f",
        ),
        (
            "Consumer Tech",
            "\u0645\u0642\u0627\u06cc\u0633\u0647 \u062f\u0648 \u0633\u0627\u0639\u062a \u0647\u0648\u0634\u0645\u0646\u062f",
        ),
    ],
)
def test_programming_filter_rejects_general_non_programming_news(category, title):
    assert not is_programming_material(
        category=category,
        title=title,
        description="",
        source_type="x_timeline",
    )


def test_programming_category_does_not_promote_empty_channel_chatter():
    assert not is_programming_material(
        category="Programming",
        title="oh yeah me too",
        description="oh yeah me too",
        source_type="telegram",
    )


@pytest.mark.parametrize(
    "title",
    [
        "https://users.rust-lang.org/u/example",
        '<table><a href="https://reddit.com/x">submitted by user</a></table>',
        "\u0627\u0634\u062a\u0631\u0627\u06a9‌\u06af\u0630\u0627\u0631\u06cc \u062f\u0631 X (\u062f\u0631 \u067e\u0646\u062c\u0631\u06c0 \u062a\u0627\u0632\u0647 \u0628\u0627\u0632 \u0645\u06cc‌\u0634\u0648\u062f)",
        "This channel is for programmers and software engineers",
        "done 👍🏻✨ react for more",
        "Hey there Alice, and welcome to our Python project! How are you?",
        "Python Django Complete Guide Price: 5.98€",
    ],
)
def test_editorial_quality_gate_rejects_navigation_and_feed_boilerplate(title):
    assert not is_usable_editorial_material(title=title, description="")
