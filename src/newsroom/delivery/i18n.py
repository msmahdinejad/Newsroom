"""Localized Telegram text loaded from package-owned resource catalogs."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from newsroom.control import ControlSnapshot

SUPPORTED_LOCALES = frozenset({"en", "fa"})
DEFAULT_LOCALE = "fa"


@lru_cache(maxsize=len(SUPPORTED_LOCALES))
def _locale(language: str) -> dict[str, Any]:
    normalized = language if language in SUPPORTED_LOCALES else DEFAULT_LOCALE
    resource = files("newsroom.resources").joinpath(
        "locales",
        f"{normalized}.json",
    )
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid locale catalog: {normalized}")
    return value


def text(language: str, key: str, **values: Any) -> str:
    """Render one localized message by stable key."""
    catalog = _locale(language)
    messages = catalog["messages"]
    template = messages.get(key)
    if template is None:
        template = _locale(DEFAULT_LOCALE)["messages"].get(key, key)
    return str(template).format(**values)


def menu_keyboard(language: str) -> dict[str, Any]:
    """Return the localized inline keyboard."""
    return {"inline_keyboard": _locale(language)["menu"]}


def bot_commands(language: str) -> list[dict[str, str]]:
    """Return commands for Telegram's native command menu."""
    return list(_locale(language)["commands"])


def help_text(snapshot: ControlSnapshot) -> str:
    """Render the complete help screen from runtime preferences."""
    catalog = _locale(snapshot.report_language)
    schedule = " | ".join(snapshot.schedule_times) if snapshot.schedule_enabled else "OFF"
    if snapshot.report_language == "fa":
        schedule = schedule.translate(
            str.maketrans(
                "0123456789",
                "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9",
            )
        )
    source_scope = (
        ", ".join(snapshot.report_source_types)
        if snapshot.report_source_types
        else str(catalog["all_sources"])
    )
    template = str(catalog["help"])
    named_digest_help = str(catalog["named_digest_help"])
    if "/report digest <slug>" not in template:
        template = template.replace(
            "\n/latest",
            f"\n{named_digest_help}\n/latest",
            1,
        )
    return template.format(
        digest_name=snapshot.digest_name,
        topic_brief=snapshot.topic_brief,
        story_count=snapshot.report_story_count,
        minimum_telegram_stories=snapshot.minimum_telegram_stories,
        source_scope=source_scope,
        schedule=schedule,
        timezone=snapshot.timezone,
    )
