"""Report-profile behavior for programming-first and platform-only digests."""

from __future__ import annotations

import pytest

from newsroom.editorial.report_profiles import (
    is_programming_material,
    is_usable_editorial_material,
    resolve_report_profile,
)


def test_default_report_is_programming_first_and_telegram_heavy():
    profile = resolve_report_profile("scheduled")

    assert profile.programming_only is True
    assert profile.source_types is None
    assert profile.minimum_telegram_stories >= profile.max_stories // 2
    assert "برنامه‌نویسی" in profile.title_fa


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
    assert profile.programming_only is True
    assert profile.comprehensive is True
    assert profile.max_stories > resolve_report_profile("scheduled").max_stories


@pytest.mark.parametrize(
    ("category", "title", "description", "source_type"),
    [
        ("APIs & Developer Tools", "Free APIs for AI applications", "", "telegram"),
        ("Programming", "کتابخانه جدید پایتون برای ساخت API", "", "telegram"),
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
        ("Sports", "تاریخچه کارت قرمز در فوتبال"),
        ("Health", "نحوه اثر داروی لاغری بر بدن"),
        ("Digital Culture", "تیزر سریال جدید منتشر شد"),
        ("Consumer Tech", "مقایسه دو ساعت هوشمند"),
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
        "اشتراک‌گذاری در X (در پنجرۀ تازه باز می‌شود)",
        "This channel is for programmers and software engineers",
        "done 👍🏻✨ react for more",
        "Hey there Alice, and welcome to our Python project! How are you?",
        "Python Django Complete Guide Price: 5.98€",
    ],
)
def test_editorial_quality_gate_rejects_navigation_and_feed_boilerplate(title):
    assert not is_usable_editorial_material(title=title, description="")
