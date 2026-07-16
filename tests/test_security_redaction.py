"""Security and redaction tests — no secrets in code, logs, or stored data."""

import re
from pathlib import Path

from newsroom.delivery.client import redact_token

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"


def test_no_hardcoded_token_in_source():
    """No hardcoded Telegram bot token in any source file."""
    token_pattern = re.compile(r'\d{6,}:[A-Za-z0-9_-]{30,}')
    for py in SRC_DIR.rglob("*.py"):
        content = py.read_text(encoding="utf-8")
        matches = token_pattern.findall(content)
        assert matches == [], f"Potential token in {py}: {matches}"


def test_redact_token_no_fragment():
    token = "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz12"
    redacted = redact_token(token)
    assert redacted == "[REDACTED]"
    assert "1234" not in redacted
    assert "4567" not in redacted
    assert "..." not in redacted
    assert token not in redacted
    assert redact_token(None) == "[REDACTED]"
    assert redact_token("") == "[REDACTED]"


def test_env_example_has_empty_token():
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for line in env_example.splitlines():
        if "TELEGRAM_BOT_TOKEN=" in line:
            assert line.strip() == "TELEGRAM_BOT_TOKEN="
            return
    raise AssertionError("TELEGRAM_BOT_TOKEN not found in .env.example")


def test_env_example_has_empty_authorized_user_ids():
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for line in env_example.splitlines():
        if "TELEGRAM_AUTHORIZED_USER_IDS=" in line:
            assert line.strip() == "TELEGRAM_AUTHORIZED_USER_IDS="
            return
    raise AssertionError("TELEGRAM_AUTHORIZED_USER_IDS not found in .env.example")


def test_env_in_gitignore():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert ".env.local" in gitignore


def test_no_token_in_models():
    """Models must not have a field for storing tokens."""
    from newsroom.storage.models import CommandRequest, Delivery, TelegramUpdate
    for model in [Delivery, TelegramUpdate, CommandRequest]:
        table = model.__table__
        for col in table.columns:
            assert "token" not in col.name.lower(), f"Token field in {model.__name__}.{col.name}"


def test_deny_message_no_secrets():
    from newsroom.delivery.access import deny_message
    msg = deny_message()
    assert "token" not in msg.lower()
    assert "secret" not in msg.lower()
    assert "password" not in msg.lower()


def test_chat_id_hashed_not_stored_raw():
    """Delivery.chat_id is a hash, not raw chat ID."""
    from newsroom.delivery.telegram import TelegramDelivery
    td = TelegramDelivery.__new__(TelegramDelivery)
    raw = "123456789"
    hashed = td._hash_chat(raw)
    assert hashed != raw
    assert len(hashed) == 16
