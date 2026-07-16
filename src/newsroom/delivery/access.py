"""Access control — fail-closed allowlist for Telegram bot commands.

No wildcard, no allow-all. Empty or malformed allowlist denies everyone.
Authorization checked on every command and every callback.
"""

from __future__ import annotations

from newsroom.config import settings


def is_authorized(user_id: int | None) -> bool:
    """Check if a Telegram user ID is in the authorized allowlist.

    Fail-closed: empty allowlist, None, or malformed entries deny everyone.
    No wildcard mode exists.
    """
    if user_id is None:
        return False
    allowed = settings.authorized_user_ids()
    if not allowed:
        return False
    return user_id in allowed


def authorized_user_ids() -> set[int]:
    """Return the parsed set of authorized user IDs."""
    return settings.authorized_user_ids()


def deny_message() -> str:
    """Generic denial message with no infrastructure details."""
    return "⛔ دسترسی غیرمجاز."
