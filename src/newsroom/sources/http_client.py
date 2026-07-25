"""Shared bounded HTTP client construction for native collectors.

The optional proxy value stays in the service environment. This module passes
it directly to HTTPX and exposes only a protocol-level transport label; it
never logs or returns the endpoint or credentials.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from newsroom.config import settings

_PROXY_SCHEMES: frozenset[str] = frozenset({"http", "https", "socks5", "socks5h"})


def _proxy_url() -> str | None:
    value = settings.collection_proxy_url.strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme.lower() not in _PROXY_SCHEMES:
        raise ValueError("unsupported collection proxy scheme")
    if not parsed.hostname:
        raise ValueError("collection proxy requires a host")
    return value


def build_collection_client(**kwargs: Any) -> httpx.AsyncClient:
    """Construct a native collector client with the configured proxy."""
    return httpx.AsyncClient(proxy=_proxy_url(), **kwargs)


def collection_transport_label() -> str:
    """Return a safe protocol-only label suitable for aggregate health."""
    value = _proxy_url()
    if value is None:
        return "direct"
    return f"{urlparse(value).scheme.lower()}_proxy"


__all__ = ["build_collection_client", "collection_transport_label"]
