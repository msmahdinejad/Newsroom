"""Production factory for the canonical local provider configuration."""

from __future__ import annotations

from pathlib import Path

from newsroom.editorial.provider import EditorialProvider
from newsroom.editorial.router.config import load_router_config
from newsroom.editorial.router.http_transport import HttpEditorialTransport
from newsroom.editorial.router.router import MultiProviderRouter
from newsroom.editorial.router.types import Clock, RouterStateSink


def create_router_from_local_env(
    path: str | Path = ".env.providers.local",
    *,
    state_sink: RouterStateSink | None = None,
    clock: Clock | None = None,
    fallback: EditorialProvider | None = None,
    validated_models: dict[str, tuple[str, ...]] | None = None,
    restored_snapshot: object | None = None,
    validate_models: bool = False,
    timeout_seconds: float = 45.0,
) -> MultiProviderRouter:
    """Create a router without consulting ambient provider access variables.

    Routes start disabled unless bounded validation is explicitly requested or
    persisted validated model IDs are supplied later by the integration layer.
    """
    config = load_router_config(path)
    transport = HttpEditorialTransport(
        config.providers,
        timeout_seconds=timeout_seconds,
        proxy_url=config.proxy_url,
    )
    router = MultiProviderRouter.from_config(
        config,
        transport=transport,
        state_sink=state_sink,
        clock=clock,
        fallback=fallback,
        validated_models=validated_models,
    )
    if validate_models:
        router.validate_models()
    if restored_snapshot is not None:
        router.restore(restored_snapshot)
    return router
