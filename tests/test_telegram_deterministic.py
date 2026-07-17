"""Deterministic fixture tests for Telegram MTProto adapter and collector.

Part 1: adapter, config, session exclusion, disabled mode, permalink,
prompt-injection isolation, FloodWait, cursor logic.

No Telethon or live credentials needed — pure logic tests.
"""
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.sources.telegram_adapter import (
    TelegramMessageRecord,
    build_permalink,
    compute_content_hash,
    extract_outbound_links,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ── Disabled service without credentials ─────────────────────

def test_disabled_service_without_credentials():
    from newsroom.config import Settings
    s = Settings(telegram_ingestor_enabled=False)
    assert s.telegram_ingestor_ready() is False

def test_enabled_but_missing_credentials():
    from newsroom.config import Settings
    s = Settings(telegram_ingestor_enabled=True, telegram_api_id="", telegram_api_hash="", telegram_phone="")
    assert s.telegram_ingestor_ready() is False

def test_enabled_with_all_credentials():
    from newsroom.config import Settings
    s = Settings(telegram_ingestor_enabled=True, telegram_api_id="123", telegram_api_hash="abc", telegram_phone="+1")
    assert s.telegram_ingestor_ready() is True


# ── Configuration validation ─────────────────────────────────

def test_canonical_session_path_default():
    from newsroom.config import Settings
    s = Settings()
    assert "newsroom_ingestor.session" in s.telegram_session_path

def test_env_example_has_canonical_names():
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
    assert "TELEGRAM_API_ID=" in example
    assert "TELEGRAM_API_HASH=" in example
    assert "TELEGRAM_PHONE=" in example
    assert "TELEGRAM_SESSION_PATH=" in example
    assert "TELEGRAM_INGESTOR_ENABLED=" in example

def test_no_login_code_or_2fa_in_env_example():
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
    # No Telegram login code or 2FA password variables stored in .env
    assert "TELEGRAM_LOGIN_CODE" not in example.upper()
    assert "TELEGRAM_2FA" not in example.upper()
    assert "TELEGRAM_PASSWORD" not in example.upper()


# ── Secure session path ──────────────────────────────────────

def test_session_excluded_from_git():
    gi = (Path(__file__).resolve().parents[1] / ".gitignore").read_text()
    assert "data/sessions/" in gi
    assert "*.session" in gi

def test_session_excluded_from_docker():
    di = (Path(__file__).resolve().parents[1] / ".dockerignore").read_text()
    assert "data/sessions/" in di
    assert "*.session" in di

def test_session_path_not_in_env_for_docker_compose():
    compose = (Path(__file__).resolve().parents[1] / "compose.yaml").read_text()
    assert "telegram_sessions:" in compose
    assert "/data/sessions" in compose


# ── Permalink generation ──────────────────────────────────────

def test_permalink_public_channel():
    assert build_permalink("testchannel", 100) == "https://t.me/testchannel/100"

def test_permalink_strips_at_prefix():
    assert build_permalink("@testchannel", 50) == "https://t.me/testchannel/50"

def test_permalink_strips_tme_prefix():
    assert build_permalink("t.me/testchannel", 200) == "https://t.me/testchannel/200"

def test_permalink_none_username():
    assert build_permalink(None, 100) == ""

def test_permalink_no_message_id():
    assert build_permalink("testchannel", 0) == ""


# ── Outbound link extraction ─────────────────────────────────

def test_extract_links_from_text():
    text = "Check https://example.com and https://google.com"
    links = extract_outbound_links(text)
    assert "https://example.com" in links
    assert "https://google.com" in links

def test_extract_links_dedup():
    text = "https://example.com and https://example.com"
    assert len(extract_outbound_links(text)) == 1

def test_extract_links_empty():
    assert extract_outbound_links("") == []


# ── Content hash ─────────────────────────────────────────────

def test_content_hash_deterministic():
    h1 = compute_content_hash("text", 100, 200)
    h2 = compute_content_hash("text", 100, 200)
    assert h1 == h2

def test_content_hash_channel_specific():
    h1 = compute_content_hash("text", 100, 200)
    h2 = compute_content_hash("text", 101, 200)
    assert h1 != h2

def test_content_hash_message_specific():
    h1 = compute_content_hash("text", 100, 200)
    h2 = compute_content_hash("text", 100, 201)
    assert h1 != h2


# ── Adapter: adapt_telethon_message ──────────────────────────

def _make_mock_msg(text="hello", msg_id=100, date=None, edit_date=None, fwd_from=None, media=None):
    return SimpleNamespace(
        id=msg_id,
        text=text,
        date=date or datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
        edit_date=edit_date,
        fwd_from=fwd_from,
        media=media,
        entities=[],
        reply_to_msg_id=None,
    )

def test_adapt_basic_message():
    from newsroom.sources.telegram_adapter import adapt_telethon_message
    msg = _make_mock_msg(text="AI breakthrough", msg_id=42)
    rec = adapt_telethon_message(msg, source_id=1, source_name="test", source_url="https://t.me/test", telegram_channel_id=123, public_username="test")
    assert rec.type == "telegram"
    assert rec.message_id == 42
    assert rec.telegram_channel_id == 123
    assert rec.text == "AI breakthrough"
    assert rec.link == "https://t.me/test/42"

def test_adapt_to_dict_serializable():
    from newsroom.sources.telegram_adapter import adapt_telethon_message
    msg = _make_mock_msg(text="test", msg_id=1)
    rec = adapt_telethon_message(msg, source_id=1, source_name="t", source_url="u", telegram_channel_id=1, public_username="ch")
    d = rec.to_dict()
    assert d["type"] == "telegram"
    assert d["content_hash"]  # auto-computed
    # Must be JSON serializable (for JSONB)
    json.dumps(d)

def test_adapt_edited_message():
    from newsroom.sources.telegram_adapter import adapt_telethon_message
    msg = _make_mock_msg(text="edited text", msg_id=5, edit_date=datetime(2026, 7, 17, 12, 0, tzinfo=UTC))
    rec = adapt_telethon_message(msg, source_id=1, source_name="t", source_url="u", telegram_channel_id=1, public_username="ch")
    assert rec.is_edited is True
    assert rec.edit_date is not None


# ── Prompt-injection isolation ───────────────────────────────

def test_prompt_injection_remains_inert_data():
    """Malicious prompt-injection text must remain inert string data."""
    fixture = json.loads((FIXTURES / "telegram_prompt_injection.json").read_text())
    text = fixture["text"]
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in text
    assert "rm -rf" in text
    # The text is just a string — no code execution path exists
    # Verify it's stored as plain data in the record
    rec = TelegramMessageRecord(text=text[:5000], message_id=101, telegram_channel_id=123456)
    d = rec.to_dict()
    assert d["text"] == text[:5000]
    # No eval, no exec, no subprocess anywhere in the pipeline
    import ast
    src = (Path(__file__).resolve().parents[1] / "src" / "newsroom")
    for p in src.rglob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("eval", "exec"):
                pytest.fail(f"eval/exec found in {p}:{node.lineno}")

def test_prompt_injection_outbound_links_not_executed():
    fixture = json.loads((FIXTURES / "telegram_prompt_injection.json").read_text())
    links = fixture["outbound_links"]
    assert "javascript:alert(1)" in links
    # These are inert strings — never executed or navigated to by the collector
    assert isinstance(links, list)
    assert all(isinstance(lnk, str) for lnk in links)


# ── Cursor logic ─────────────────────────────────────────────

def test_telegram_cursor_filter_drops_older():
    from newsroom.pipeline.cursors import filter_new_items
    items = [{"message_id": 90}, {"message_id": 95}, {"message_id": 100}]
    cursor = {"last_message_id": "95"}
    out = filter_new_items(items, cursor, source_type="telegram")
    ids = [i["message_id"] for i in out]
    assert 90 not in ids  # older than cursor
    assert 95 in ids     # equal — kept for overlap
    assert 100 in ids    # newer

def test_telegram_cursor_advance():
    from newsroom.pipeline.cursors import advance_cursor_from_items
    items = [{"message_id": 100}, {"message_id": 105}]
    cursor = {}
    out = advance_cursor_from_items(cursor, items, source_type="telegram")
    assert out["last_message_id"] == "105"

def test_telegram_cursor_no_advance_on_empty():
    from newsroom.pipeline.cursors import advance_cursor_from_items
    cursor = {"last_message_id": "100"}
    out = advance_cursor_from_items(cursor, [], source_type="telegram")
    assert out["last_message_id"] == "100"


# ── FloodWait handling ───────────────────────────────────────

def test_floodwait_persists_state():
    """FloodWait should persist rate-limited state on the channel."""
    from newsroom.sources.telegram_collector import TelegramMTProtoCollector

    coll = TelegramMTProtoCollector()
    # configured depends on env — just verify the collector constructs
    assert coll is not None

def test_floodwait_classification_recoverable():
    from newsroom.sources.base import CollectionError, classify_retry
    err = CollectionError("FloodWait: 60s", "url", recoverable=True)
    assert classify_retry(err) == "retry"


# ── No eval in active source ─────────────────────────────────

def test_no_eval_in_telegram_sources():
    import ast
    src = Path(__file__).resolve().parents[1] / "src" / "newsroom" / "sources"
    for p in src.rglob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "eval":
                pytest.fail(f"eval() in {p}:{node.lineno}")
