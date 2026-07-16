"""Access control tests — fail-closed, no wildcard, numeric ID validation."""

from unittest.mock import patch

from newsroom.delivery.access import authorized_user_ids, deny_message, is_authorized


def test_empty_allowlist_denies_everyone():
    with patch("newsroom.delivery.access.settings") as mock_settings:
        mock_settings.authorized_user_ids.return_value = set()
        assert is_authorized(123456) is False
        assert is_authorized(0) is False
        assert is_authorized(None) is False


def test_authorized_user_allowed():
    with patch("newsroom.delivery.access.settings") as mock_settings:
        mock_settings.authorized_user_ids.return_value = {123456}
        assert is_authorized(123456) is True


def test_unauthorized_user_denied():
    with patch("newsroom.delivery.access.settings") as mock_settings:
        mock_settings.authorized_user_ids.return_value = {123456}
        assert is_authorized(999999) is False


def test_none_user_id_denied():
    with patch("newsroom.delivery.access.settings") as mock_settings:
        mock_settings.authorized_user_ids.return_value = {123456}
        assert is_authorized(None) is False


def test_no_wildcard_mode():
    """No wildcard or allow-all mode exists — every ID must be explicitly listed."""
    with patch("newsroom.delivery.access.settings") as mock_settings:
        mock_settings.authorized_user_ids.return_value = {123}
        assert is_authorized(456) is False
        assert is_authorized("*") is False
        assert is_authorized(0) is False


def test_malformed_allowlist_denies_safely():
    """Malformed entries are skipped, not treated as wildcards."""
    with patch("newsroom.delivery.access.settings") as mock_settings:
        mock_settings.authorized_user_ids.return_value = set()
        # Simulate the config parsing: "abc, 123, xyz" → {123}
        mock_settings.authorized_user_ids.return_value = {123}
        assert is_authorized(123) is True
        assert is_authorized("abc") is False
        assert is_authorized("xyz") is False


def test_multiple_authorized_users():
    with patch("newsroom.delivery.access.settings") as mock_settings:
        mock_settings.authorized_user_ids.return_value = {111, 222, 333}
        assert is_authorized(111) is True
        assert is_authorized(222) is True
        assert is_authorized(333) is True
        assert is_authorized(444) is False


def test_deny_message_no_infrastructure_details():
    msg = deny_message()
    assert "دسترسی" in msg
    # Must not contain infrastructure details
    assert "token" not in msg.lower()
    assert "database" not in msg.lower()
    assert "api" not in msg.lower()
    assert "config" not in msg.lower()
    assert "password" not in msg.lower()


def test_authorized_user_ids_returns_set():
    """Config parser returns a set of integers."""
    with patch("newsroom.delivery.access.settings") as mock_settings:
        mock_settings.authorized_user_ids.return_value = {123, 456}
        ids = authorized_user_ids()
        assert isinstance(ids, set)
        assert 123 in ids
        assert 456 in ids


def test_config_parsing_numeric_ids():
    """Settings.authorized_user_ids() parses comma-separated numeric IDs."""
    from newsroom.config import Settings

    s = Settings(telegram_authorized_users="123,456,789")
    ids = s.authorized_user_ids()
    assert ids == {123, 456, 789}


def test_config_parsing_empty_string():
    from newsroom.config import Settings

    s = Settings(telegram_authorized_users="")
    assert s.authorized_user_ids() == set()


def test_config_parsing_malformed_entries_skipped():
    from newsroom.config import Settings

    s = Settings(telegram_authorized_users="123,abc,456,xyz,789")
    ids = s.authorized_user_ids()
    assert ids == {123, 456, 789}


def test_config_parsing_whitespace_trimmed():
    from newsroom.config import Settings

    s = Settings(telegram_authorized_users="  123  ,  456  ")
    ids = s.authorized_user_ids()
    assert ids == {123, 456}


def test_config_parsing_duplicates_deduped():
    from newsroom.config import Settings

    s = Settings(telegram_authorized_users="123,123,456")
    ids = s.authorized_user_ids()
    assert ids == {123, 456}
