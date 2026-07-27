"""Public release audit policy tests."""

from scripts.audit_public_release import SECRET_KEY_PATTERN


def test_protected_local_identity_and_access_names_are_covered() -> None:
    protected = {
        "GEMINI_API_KEYS",
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_PHONE",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_AUTHORIZED_USER_IDS",
        "TELEGRAM_PROXY_URL",
        "TELEGRAM_MTPROXY_HOST",
        "TELEGRAM_MTPROXY_SECRET",
        "POSTGRES_PASSWORD",
        "TWITTER_AUTH_TOKEN",
        "TWITTER_CT0",
    }

    assert all(SECRET_KEY_PATTERN.search(name) for name in protected)
