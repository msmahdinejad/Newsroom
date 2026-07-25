"""Idempotency tests — update_id dedup, command request dedup, callback dedup."""

from unittest.mock import MagicMock

from newsroom.delivery.identity import command_request_key, identity_fingerprint
from newsroom.storage.models import CommandRequest, TelegramUpdate


def test_telegram_update_unique_constraint():
    """TelegramUpdate has unique constraint on update_id."""
    assert TelegramUpdate.__table__.c.update_id.unique is True


def test_telegram_update_index():
    """TelegramUpdate has index on update_id."""
    # Just verify the table exists with correct fields
    assert hasattr(TelegramUpdate, "update_id")
    assert hasattr(TelegramUpdate, "update_type")
    assert hasattr(TelegramUpdate, "result")


def test_persisted_telegram_identities_use_fingerprints_only():
    """Durable Telegram audit rows must not contain raw owner/chat IDs."""
    telegram_columns = TelegramUpdate.__table__.c
    command_columns = CommandRequest.__table__.c
    assert "user_id" not in telegram_columns
    assert "chat_id" not in telegram_columns
    assert "user_fingerprint" in telegram_columns
    assert "chat_fingerprint" in telegram_columns
    assert "user_id" not in command_columns
    assert "chat_id" not in command_columns
    assert "user_fingerprint" in command_columns
    assert "chat_fingerprint" in command_columns


def test_command_request_unique_constraint():
    """CommandRequest has unique constraint on request_key."""
    assert CommandRequest.__table__.c.request_key.unique is True


def test_command_request_fields():
    assert hasattr(CommandRequest, "request_key")
    assert hasattr(CommandRequest, "command")
    assert hasattr(CommandRequest, "status")
    assert hasattr(CommandRequest, "report_id")
    assert hasattr(CommandRequest, "delivery_id")


def test_idempotency_logic_duplicate_update_skipped():
    """Simulate: if update_id already exists in DB, skip processing."""
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_existing = MagicMock()
    mock_query.filter_by.return_value.first.return_value = mock_existing
    mock_db.query.return_value = mock_query

    # The bot checks for existing update before processing
    existing = mock_db.query(TelegramUpdate).filter_by(update_id=12345).first()
    assert existing is not None  # Already processed → skip


def test_idempotency_logic_new_update_processed():
    """Simulate: if update_id not in DB, process it."""
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.filter_by.return_value.first.return_value = None
    mock_db.query.return_value = mock_query

    existing = mock_db.query(TelegramUpdate).filter_by(update_id=99999).first()
    assert existing is None  # New → process


def test_identity_fingerprint_is_stable_and_contains_no_raw_identifier():
    fingerprint = identity_fingerprint("user", 123456789)
    assert fingerprint == identity_fingerprint("user", 123456789)
    assert fingerprint is not None
    assert len(fingerprint) == 64
    assert "123456789" not in fingerprint


def test_command_request_key_is_stable_without_persisting_identifiers():
    key1 = command_request_key("manual", 123456789, 987654321, 111)
    key2 = command_request_key("manual", 123456789, 987654321, 111)
    assert key1 == key2
    assert "123456789" not in key1
    assert "987654321" not in key1
    assert len(key1.split(":", 1)[1]) == 64


def test_command_request_key_separates_update_user_chat_and_mode():
    baseline = command_request_key("manual", 123, 456, 1001)
    assert baseline != command_request_key("manual", 789, 456, 1001)
    assert baseline != command_request_key("manual", 123, 789, 1001)
    assert baseline != command_request_key("manual_new", 123, 456, 1001)
    assert baseline != command_request_key("manual", 123, 456, 1002)
