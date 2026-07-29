"""Bounded provider model discovery; discovered routes remain disabled."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from newsroom.editorial.router.protocols import protocol_api_base
from newsroom.editorial.router.types import ProviderConfig

_NON_EDITORIAL_MODEL_MARKERS = (
    "audio",
    "compound",
    "deplot",
    "embedding",
    "guard",
    "image",
    "imagen",
    "moderation",
    "ocr",
    "orpheus",
    "rerank",
    "speech",
    "transcri",
    "tts",
    "veo",
    "whisper",
)


@dataclass(frozen=True)
class ModelCatalogResult:
    """Safe discovery metadata with no provider access values."""

    provider: str
    status: str
    models: tuple[str, ...]
    failure_category: str | None = None


class ProviderModelCatalog:
    """List generation-capable model IDs through supported protocol adapters."""

    def __init__(
        self,
        providers: tuple[ProviderConfig, ...],
        *,
        timeout_seconds: float = 20.0,
        proxy_url: str | None = None,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
    ) -> None:
        self.providers = providers
        self.timeout_seconds = max(1.0, timeout_seconds)
        self.proxy_url = proxy_url
        self.client_factory = client_factory

    def discover(
        self,
        *,
        provider: str | None = None,
        max_models: int = 50,
    ) -> tuple[ModelCatalogResult, ...]:
        limit = max(1, min(100, max_models))
        return tuple(
            self._discover_one(config, limit)
            for config in self.providers
            if provider is None or config.name == provider
        )

    def _discover_one(
        self,
        provider: ProviderConfig,
        limit: int,
    ) -> ModelCatalogResult:
        if not provider.keys:
            return ModelCatalogResult(provider.name, "unavailable", ())
        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(
                self.timeout_seconds,
                connect=min(10.0, self.timeout_seconds),
            )
        }
        if self.proxy_url:
            client_kwargs["proxy"] = self.proxy_url
        try:
            with self.client_factory(**client_kwargs) as client:
                for key_value in provider.keys:
                    request = _catalog_request(provider, key_value)
                    models: list[str] = []
                    params = _first_page(provider.protocol, limit)
                    failure: str | None = None
                    for _page in range(5):
                        response = client.get(
                            request.url,
                            headers=request.headers,
                            params=params,
                        )
                        failure = _catalog_failure(response)
                        if failure == "invalid_key":
                            break
                        if failure is not None:
                            return ModelCatalogResult(
                                provider.name,
                                "failed",
                                (),
                                failure,
                            )
                        response.raise_for_status()
                        body = response.json()
                        for model in _parse_models(provider, body):
                            if model not in models:
                                models.append(model)
                            if len(models) >= limit:
                                break
                        if len(models) >= limit:
                            break
                        params = _next_page(provider.protocol, body)
                        if not params:
                            break
                    if failure != "invalid_key":
                        return ModelCatalogResult(
                            provider.name,
                            "discovered",
                            tuple(models[:limit]),
                        )
            return ModelCatalogResult(
                provider.name,
                "failed",
                (),
                "invalid_key",
            )
        except (httpx.TimeoutException, httpx.NetworkError):
            return ModelCatalogResult(
                provider.name,
                "failed",
                (),
                "network_error",
            )
        except (httpx.HTTPError, TypeError, ValueError, KeyError):
            return ModelCatalogResult(
                provider.name,
                "failed",
                (),
                "malformed_catalog",
            )


def _catalog_failure(response: httpx.Response) -> str | None:
    if response.status_code in {401, 403}:
        return "invalid_key"
    if response.status_code == 429:
        return "rate_limit"
    if response.status_code >= 500:
        return "server_error"
    return None


def _first_page(protocol: str, limit: int) -> dict[str, str | int]:
    if protocol == "gemini":
        return {"pageSize": min(100, limit)}
    if protocol == "anthropic":
        return {"limit": min(100, limit)}
    return {}


@dataclass(frozen=True)
class _CatalogRequest:
    url: str
    headers: dict[str, str] = field(repr=False)


def _catalog_request(provider: ProviderConfig, key_value: str) -> _CatalogRequest:
    base = protocol_api_base(provider.api_base, provider.protocol)
    if provider.protocol == "gemini":
        return _CatalogRequest(
            f"{base}/models",
            {"x-goog-api-key": key_value},
        )
    if provider.protocol == "anthropic":
        return _CatalogRequest(
            f"{base}/models",
            {
                "x-api-key": key_value,
                "anthropic-version": "2023-06-01",
            },
        )
    return _CatalogRequest(
        f"{base}/models",
        {"Authorization": f"Bearer {key_value}"},
    )


def _parse_models(provider: ProviderConfig, body: Any) -> list[str]:
    rows = body.get("models" if provider.protocol == "gemini" else "data") or []
    models: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if provider.protocol == "gemini":
            methods = row.get("supportedGenerationMethods") or []
            if "generateContent" not in methods:
                continue
            model = str(row.get("name") or "").removeprefix("models/")
        else:
            model = str(row.get("id") or "")
        model = _canonical_model_id(provider, model)
        if _is_editorial_candidate(model) and model not in models:
            models.append(model)
    return models


def _canonical_model_id(provider: ProviderConfig, model: str) -> str:
    api_hostname = (urlparse(provider.api_base).hostname or "").casefold()
    if provider.name == "gemini" or api_hostname == "generativelanguage.googleapis.com":
        return model.removeprefix("models/")
    return model


def _is_editorial_candidate(model: str) -> bool:
    normalized = model.casefold()
    if not normalized:
        return False
    if normalized.rsplit("/", maxsplit=1)[-1].startswith(("bge-", "e5-")):
        return False
    return not any(marker in normalized for marker in _NON_EDITORIAL_MODEL_MARKERS)


def _next_page(protocol: str, body: Any) -> dict[str, str | int]:
    if protocol == "gemini":
        token = str(body.get("nextPageToken") or "")
        return {"pageToken": token, "pageSize": 100} if token else {}
    if protocol == "anthropic" and body.get("has_more"):
        last_id = str(body.get("last_id") or "")
        return {"after_id": last_id, "limit": 100} if last_id else {}
    return {}
