"""Gate 6 production connector ownership, bounds, and secret-scope tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
PIN = "1494c2ab239e7355a77e7cceaf3271453a1f34b5"


def test_compose_has_single_mtproto_owner_and_isolated_x_env() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    collector = compose.split("  collector:", 1)[1].split("  report-worker:", 1)[0]
    ingestor = compose.split("  telegram-ingestor:", 1)[1].split("  # Gate 5:", 1)[0]
    agent_worker = compose.split("  agent-reach-worker:", 1)[1].split(
        "  # One-time authorization", 1
    )[0]

    assert "TELEGRAM_API_ID" not in collector
    assert "telegram_sessions" not in collector
    assert 'exclude_source_types={"telegram", "x_timeline"}' in collector
    assert "telegram_sessions:/data/sessions" in ingestor
    assert "- path: .env.x.local" in agent_worker
    assert PIN in agent_worker
    assert "newsroom.sources.agent_reach.worker" in agent_worker
    assert "TELEGRAM_API_HASH:" not in agent_worker
    assert "EDITORIAL_API_KEY:" not in agent_worker


def test_compose_scopes_protected_configuration_to_required_services() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    report_worker = compose.split("  report-worker:", 1)[1].split("  scheduler:", 1)[0]
    scheduler = compose.split("  scheduler:", 1)[1].split("  telegram-bot:", 1)[0]
    telegram_bot = compose.split("  telegram-bot:", 1)[1].split(
        "  telegram-ingestor:", 1
    )[0]
    ingestor = compose.split("  telegram-ingestor:", 1)[1].split("  # Gate 5:", 1)[0]
    agent_worker = compose.split("  agent-reach-worker:", 1)[1].split(
        "  # One-time authorization", 1
    )[0]

    assert ".env.providers.local" not in report_worker
    assert "TELEGRAM_" not in report_worker
    assert "TELEGRAM_AUTHORIZED_USER_IDS" not in scheduler
    assert "TELEGRAM_API_" not in scheduler
    assert ".env.providers.local" in scheduler
    assert ".env.providers.local" in telegram_bot
    assert "TELEGRAM_API_" not in telegram_bot
    assert ".env.providers.local" not in ingestor
    assert "TELEGRAM_BOT_TOKEN" not in ingestor
    assert ".env.providers.local" not in agent_worker
    assert "TELEGRAM_BOT_TOKEN:" not in agent_worker
    assert "TELEGRAM_API_HASH:" not in agent_worker


def test_external_source_dependencies_are_immutable() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert f"Agent-Reach/archive/{PIN}.zip" in project
    assert '"twitter-cli==0.8.5"' in project
    assert "--extra external-sources" in dockerfile
    assert f"ARG AGENT_REACH_PINNED_SHA={PIN}" in dockerfile


def _telegram_settings(**overrides):
    values = {
        "telegram_connection_mode": "direct",
        "telegram_mtproxy_host": "",
        "telegram_mtproxy_secret": "",
        "telegram_mtproxy_port": 0,
        "telegram_proxy_type": "",
        "telegram_proxy_url": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_telegram_direct_transport_is_default() -> None:
    from newsroom.sources import telegram_collector

    with patch.object(telegram_collector, "settings", _telegram_settings()):
        kwargs, label = telegram_collector.telegram_transport_config()
    assert kwargs == {}
    assert label == "direct"


def test_telegram_socks_transport_never_exposes_url_in_label() -> None:
    from newsroom.sources import telegram_collector

    local = _telegram_settings(telegram_proxy_url="socks5://user:pass@127.0.0.1:1080")
    with patch.object(telegram_collector, "settings", local):
        kwargs, label = telegram_collector.telegram_transport_config()
    assert label == "socks5"
    assert "127.0.0.1" not in label
    assert "user" not in label
    assert kwargs["proxy"][2] == 1080


def test_telegram_explicit_socks_type_supports_host_port_url() -> None:
    from newsroom.sources import telegram_collector

    local = _telegram_settings(
        telegram_proxy_type="socks5",
        telegram_proxy_url="proxy.test:9443",
    )
    with patch.object(telegram_collector, "settings", local):
        kwargs, label = telegram_collector.telegram_transport_config()
    assert label == "socks5"
    assert kwargs["proxy"][1:4] == ("proxy.test", 9443, True)


def test_telegram_obfuscated_connection_supports_socks_proxy() -> None:
    from telethon.network.connection.tcpobfuscated import ConnectionTcpObfuscated

    from newsroom.sources import telegram_collector

    local = _telegram_settings(
        telegram_connection_mode="obfuscated",
        telegram_proxy_type="socks5",
        telegram_proxy_url="proxy.test:9443",
    )
    with patch.object(telegram_collector, "settings", local):
        kwargs, label = telegram_collector.telegram_transport_config()
    assert kwargs["connection"] is ConnectionTcpObfuscated
    assert label == "obfuscated+socks5"


def test_telegram_http_proxy_is_supported() -> None:
    from newsroom.sources import telegram_collector

    local = _telegram_settings(telegram_proxy_url="http://proxy.test:8080")
    with patch.object(telegram_collector, "settings", local):
        kwargs, label = telegram_collector.telegram_transport_config()
    assert label == "http"
    assert kwargs["proxy"][1:4] == ("proxy.test", 8080, True)


def test_mtproxy_requires_explicit_connection_mode() -> None:
    from newsroom.sources import telegram_collector

    local = _telegram_settings(
        telegram_connection_mode="direct",
        telegram_mtproxy_host="proxy.invalid",
        telegram_mtproxy_port=443,
        telegram_mtproxy_secret="dd" + ("0" * 32),
    )
    with patch.object(telegram_collector, "settings", local):
        kwargs, label = telegram_collector.telegram_transport_config()
    assert kwargs == {}
    assert label == "direct"


def test_complete_mtproxy_uses_mtproxy_connection() -> None:
    from telethon.network.connection.tcpmtproxy import (
        ConnectionTcpMTProxyRandomizedIntermediate,
    )

    from newsroom.sources import telegram_collector

    local = _telegram_settings(
        telegram_connection_mode="mtproxy",
        telegram_mtproxy_host="proxy.test",
        telegram_mtproxy_port=443,
        telegram_mtproxy_secret="dd" + ("0" * 32),
    )
    with patch.object(telegram_collector, "settings", local):
        kwargs, label = telegram_collector.telegram_transport_config()
    assert label == "mtproxy"
    assert kwargs["connection"] is ConnectionTcpMTProxyRandomizedIntermediate
    assert kwargs["proxy"][0:2] == ("proxy.test", 443)


def test_incomplete_mtproxy_fails_closed() -> None:
    from newsroom.sources import telegram_collector
    from newsroom.sources.base import CollectionError

    local = _telegram_settings(
        telegram_connection_mode="mtproxy",
        telegram_mtproxy_host="proxy.invalid",
    )
    with patch.object(telegram_collector, "settings", local), pytest.raises(CollectionError):
        telegram_collector.telegram_transport_config()


def test_compose_passes_safe_telegram_transport_controls() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    ingestor = compose.split("  telegram-ingestor:", 1)[1].split("  # Gate 5:", 1)[0]
    authorize = compose.split("  telegram-authorize:", 1)[1].split("volumes:", 1)[0]
    for service in (ingestor, authorize):
        assert "TELEGRAM_PROXY_TYPE:" in service
        assert "TELEGRAM_CONNECTION_MODE:" in service


def test_telegram_handle_extraction_supports_public_links() -> None:
    from newsroom.sources.telegram_ingestor_service import _channel_handle

    source = SimpleNamespace(config={}, url="https://t.me/s/public_channel")
    assert _channel_handle(source) == "public_channel"
    source = SimpleNamespace(config={"channel_username": "@configured"}, url="")
    assert _channel_handle(source) == "configured"


def test_permanent_telegram_identity_failure_deactivates_source_and_inventory() -> None:
    from newsroom.sources.telegram_ingestor_service import _record_channel_failure
    from newsroom.storage.models import SourceInventory

    source = SimpleNamespace(
        id=7,
        enabled=True,
        health_status="healthy",
        inactive_reason=None,
        no_cursor_reason=None,
    )
    inventory = SimpleNamespace(operational_state="active", inactive_reason=None)
    query = MagicMock()
    query.filter_by.return_value.first.return_value = inventory
    db = MagicMock()
    db.query.return_value = query

    _record_channel_failure(db, source, "channel_unresolvable")

    assert source.enabled is False
    assert source.health_status == "unavailable"
    assert source.inactive_reason == "channel_unresolvable"
    assert source.no_cursor_reason == "channel_unresolvable"
    assert inventory.operational_state == "inactive"
    assert inventory.inactive_reason == "channel_unresolvable"
    db.query.assert_called_once_with(SourceInventory)


def test_ingestor_healthcheck_fails_when_enabled_but_disconnected(capsys) -> None:
    from newsroom import service_status

    payload = {"status": "enabled", "healthy": False, "connection_status": "connection_failed"}
    with patch.object(service_status, "telegram_ingestor_status", return_value=payload):
        assert service_status.main(["ingestor"]) == 1
    assert json.loads(capsys.readouterr().out)["healthy"] is False


def test_ingestor_passes_attached_source_to_collector() -> None:
    from contextlib import contextmanager
    from datetime import UTC, datetime

    from newsroom.sources import telegram_ingestor_service as service
    from newsroom.storage.models import CollectionRun, Source, TelegramChannel

    source = SimpleNamespace(
        id=1,
        type="telegram",
        enabled=True,
        config={"channel_username": "public_channel"},
        url="https://t.me/public_channel",
        last_attempt_at=None,
        last_success_at=None,
        last_error_at=None,
        failure_category=None,
        validation_status=None,
        consecutive_failures=0,
        health_status="configured",
        last_error=None,
        no_cursor_reason=None,
    )
    channel = SimpleNamespace(
        source_id=1,
        public_username="public_channel",
        telegram_channel_id=123,
        enabled=True,
        last_message_id=0,
    )

    class _Query:
        def __init__(self, model):
            self.model = model

        def filter(self, *_args):
            return self

        def filter_by(self, **_kwargs):
            return self

        def all(self):
            return [source] if self.model is Source else []

        def first(self):
            return channel if self.model is TelegramChannel else None

    class _SqlAlchemySession:
        def __init__(self):
            self.detached: set[int] = set()
            self.runs: dict[int, object] = {}

        def query(self, model):
            return _Query(model)

        def add(self, value):
            if isinstance(value, CollectionRun):
                value.id = len(self.runs) + 1
                self.runs[value.id] = value

        def flush(self):
            return None

        def commit(self):
            return None

        def expunge(self, value):
            self.detached.add(id(value))

        def merge(self, value):
            return value

        def get(self, model, value_id):
            return self.runs.get(value_id) if model is CollectionRun else None

    _SqlAlchemySession.__module__ = "sqlalchemy.testing"
    db = _SqlAlchemySession()

    class _Collector:
        async def collect(self, value):
            assert id(value) not in db.detached
            return []

        def persist_items(self, *_args):
            return {"new": 0, "updated": 0, "skipped": 0}

        def detect_gaps(self, *_args):
            return []

    @contextmanager
    def _db():
        yield db

    local_settings = SimpleNamespace(
        telegram_max_sources_per_cycle=1,
        telegram_source_spacing_seconds=0,
    )
    with (
        patch.object(service, "get_db", _db),
        patch.object(service, "settings", local_settings),
        patch.object(service, "load_cursor", return_value={}),
        patch.object(service, "save_cursor"),
    ):
        result = asyncio.run(service._collect_all_channels(_Collector()))

    assert result["failed"] == []
    assert result["channels"] == [
        {"source_id": 1, "new": 0, "updated": 0, "skipped": 0, "gaps": 0}
    ]
    assert source.last_success_at <= datetime.now(UTC)


class _InventoryQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def all(self):
        return self.rows


class _SourceQuery:
    def __init__(self, session):
        self.session = session
        self.filters = {}

    def filter_by(self, **kwargs):
        self.filters = kwargs
        return self

    def first(self):
        for source in self.session.sources:
            if all(getattr(source, key, None) == value for key, value in self.filters.items()):
                return source
        return None


class _ActivationSession:
    def __init__(self, rows):
        from newsroom.storage.models import SourceInventory

        self.rows = rows
        self.sources = []
        self.inventory_model = SourceInventory

    def query(self, model):
        from newsroom.storage.models import Source

        if model is self.inventory_model:
            return _InventoryQuery(self.rows)
        if model is Source:
            return _SourceQuery(self)
        raise AssertionError(model)

    def add(self, value):
        from newsroom.storage.models import Source

        if isinstance(value, Source):
            value.id = len(self.sources) + 1
            self.sources.append(value)

    def flush(self):
        return None

    def get(self, _model, source_id):
        return next((source for source in self.sources if source.id == source_id), None)


def test_x_activation_persists_only_safe_env_references(monkeypatch) -> None:
    from newsroom.sources.agent_reach.worker import activate_x_inventory_sources
    from newsroom.storage.models import SourceInventory

    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "forbidden-access-value")
    monkeypatch.setenv("TWITTER_CT0", "forbidden-csrf-value")
    row = SourceInventory(
        workbook_id=1,
        platform="X / Twitter",
        workbook_type="Account",
        name="Example",
        handle="example_handle",
        public_url="https://x.com/example_handle",
        stable_identity="a" * 64,
        mapped_type="x_timeline",
        validation_result="ok",
        operational_state="inactive",
        coverage_score=1,
    )
    session = _ActivationSession([row])
    report = activate_x_inventory_sources(session)  # type: ignore[arg-type]

    assert report["activated"] == 1
    source = session.sources[0]
    serialized = json.dumps(source.config)
    assert source.config["auth_token_env"] == "TWITTER_AUTH_TOKEN"
    assert source.config["ct0_env"] == "TWITTER_CT0"
    assert "forbidden-access-value" not in serialized
    assert "forbidden-csrf-value" not in serialized
    assert row.operational_state == "inactive"
    assert row.inactive_reason == "x_pending_live_validation"
    assert source.enabled is False


def test_x_failures_are_reduced_to_safe_categories() -> None:
    from newsroom.pipeline.gate5_collect import _safe_collection_failure_category
    from newsroom.sources.base import CollectionError

    assert (
        _safe_collection_failure_category(
            CollectionError("provider returned 429 rate limit", ""), "x_timeline"
        )
        == "x_rate_limit"
    )
    assert (
        _safe_collection_failure_category(
            CollectionError("numeric account ID missing", ""), "x_timeline"
        )
        == "x_inaccessible"
    )
    assert (
        _safe_collection_failure_category(
            CollectionError("ClientTransaction initialization failed", ""), "x_timeline"
        )
        == "x_upstream_client_error"
    )


def test_native_collector_can_exclude_stateful_owners() -> None:
    from newsroom.pipeline.collect import collect_sources

    telegram = SimpleNamespace(id=1, type="telegram", enabled=True)
    x_source = SimpleNamespace(id=2, type="x_timeline", enabled=True)
    query = MagicMock()
    query.filter.return_value = query
    query.all.return_value = [telegram, x_source]
    session = MagicMock()
    session.query.return_value = query
    result = asyncio.run(
        collect_sources(session, exclude_source_types={"telegram", "x_timeline"})
    )
    assert result["sources"] == 0
    session.add.assert_not_called()
