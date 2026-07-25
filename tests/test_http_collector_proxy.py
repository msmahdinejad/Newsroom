"""Shared proxy configuration for native HTTP collectors."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_collection_client_uses_configured_socks_proxy() -> None:
    from newsroom.sources import http_client

    local_settings = MagicMock(collection_proxy_url="socks5://proxy.invalid:1080")
    with (
        patch.object(http_client, "settings", local_settings),
        patch.object(http_client.httpx, "AsyncClient") as client,
    ):
        http_client.build_collection_client(timeout=MagicMock())

    assert client.call_args.kwargs["proxy"] == "socks5://proxy.invalid:1080"


def test_collection_client_uses_direct_mode_when_proxy_is_empty() -> None:
    from newsroom.sources import http_client

    local_settings = MagicMock(collection_proxy_url="")
    with (
        patch.object(http_client, "settings", local_settings),
        patch.object(http_client.httpx, "AsyncClient") as client,
    ):
        http_client.build_collection_client(timeout=MagicMock())

    assert client.call_args.kwargs["proxy"] is None


def test_collection_client_rejects_unsupported_proxy_scheme() -> None:
    from newsroom.sources import http_client

    local_settings = MagicMock(collection_proxy_url="ftp://proxy.invalid:21")
    with (
        patch.object(http_client, "settings", local_settings),
        pytest.raises(ValueError, match="unsupported collection proxy scheme"),
    ):
        http_client.build_collection_client(timeout=MagicMock())


def test_proxy_transport_label_never_contains_endpoint() -> None:
    from newsroom.sources import http_client

    local_settings = MagicMock(collection_proxy_url="socks5://proxy.invalid:1080")
    with patch.object(http_client, "settings", local_settings):
        assert http_client.collection_transport_label() == "socks5_proxy"
