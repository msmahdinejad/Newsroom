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


def test_external_source_dependencies_are_immutable() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert f"Agent-Reach/archive/{PIN}.zip" in project
    assert '"twitter-cli==0.8.5"' in project
    assert "--extra external-sources" in dockerfile
    assert f"ARG AGENT_REACH_PINNED_SHA={PIN}" in dockerfile


def _telegram_settings(**overrides):
    values = {
        "telegram_mtproxy_host": "",
        "telegram_mtproxy_secret": "",
        "telegram_mtproxy_port": 0,
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


def test_incomplete_mtproxy_fails_closed() -> None:
    from newsroom.sources import telegram_collector
    from newsroom.sources.base import CollectionError

    local = _telegram_settings(telegram_mtproxy_host="proxy.invalid")
    with patch.object(telegram_collector, "settings", local), pytest.raises(CollectionError):
        telegram_collector.telegram_transport_config()


def test_telegram_handle_extraction_supports_public_links() -> None:
    from newsroom.sources.telegram_ingestor_service import _channel_handle

    source = SimpleNamespace(config={}, url="https://t.me/s/public_channel")
    assert _channel_handle(source) == "public_channel"
    source = SimpleNamespace(config={"channel_username": "@configured"}, url="")
    assert _channel_handle(source) == "configured"


def test_ingestor_healthcheck_fails_when_enabled_but_disconnected(capsys) -> None:
    from newsroom import service_status

    payload = {"status": "enabled", "healthy": False, "connection_status": "connection_failed"}
    with patch.object(service_status, "telegram_ingestor_status", return_value=payload):
        assert service_status.main(["ingestor"]) == 1
    assert json.loads(capsys.readouterr().out)["healthy"] is False


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
