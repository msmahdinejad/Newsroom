"""Canonical `.env.providers.local` loader for editorial provider access."""

from __future__ import annotations

import math
import re
from pathlib import Path

from dotenv import dotenv_values

from newsroom.editorial.router.types import ProviderConfig, RateLimits, RouterConfig

DEFAULT_MODELS: dict[str, tuple[str, ...]] = {
    "gemini": (
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
    ),
    "mistral": ("mistral-medium-3-5", "mistral-large-2512", "mistral-small-2603"),
    "groq": ("openai/gpt-oss-120b", "llama-3.3-70b-versatile"),
    "nvidia": ("nvidia/nemotron-3-ultra-550b-a55b",),
}

DEFAULT_BASES = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "mistral": "https://api.mistral.ai/v1",
    "groq": "https://api.groq.com/openai/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
}


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(part for part in re.split(r"[,;\s]+", value or "") if part)


def _int(values: dict[str, str | None], name: str, default: int) -> int:
    try:
        return max(1, int(values.get(name) or default))
    except (TypeError, ValueError):
        return default


def _float(values: dict[str, str | None], name: str, default: float) -> float:
    try:
        return max(0.0, float(values.get(name) or default))
    except (TypeError, ValueError):
        return default


def _bool(values: dict[str, str | None], name: str, default: bool = False) -> bool:
    raw = values.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def load_router_config(path: str | Path = ".env.providers.local") -> RouterConfig:
    """Load provider access only from the explicit local provider file.

    `dotenv_values` deliberately ignores ambient provider variables. The
    resulting dataclasses hide key values from repr and expose no serializer.
    """

    provider_path = Path(path)
    if provider_path.name != ".env.providers.local":
        raise ValueError("provider configuration must use the canonical .env.providers.local filename")
    values = (
        dict(dotenv_values(provider_path, interpolate=False))
        if provider_path.is_file()
        else {}
    )
    order = tuple(p.lower() for p in _split(values.get("LLM_PROVIDER_ORDER")))
    if not order:
        order = ("gemini", "mistral", "groq", "nvidia")

    headroom = min(1.0, _float(values, "LLM_RATE_HEADROOM", 0.8))
    providers: list[ProviderConfig] = []
    for name in order:
        upper = name.upper()
        keys = _split(values.get(f"{upper}_API_KEYS"))
        configured_models = _split(values.get(f"{upper}_MODELS"))
        models = configured_models or DEFAULT_MODELS.get(name, ())
        if "mistral-small-2506" in models:
            models = tuple(model for model in models if model != "mistral-small-2506")

        if name == "gemini":
            advertised_rpm = _int(values, "GEMINI_LIMIT_RPM", 15)
            advertised_tpm = _int(values, "GEMINI_LIMIT_TPM", 250_000)
            advertised_rpd = _int(values, "GEMINI_LIMIT_RPD", 500)
            limits = RateLimits(
                rpm=max(1, math.floor(advertised_rpm * headroom)),
                tpm=max(1, math.floor(advertised_tpm * headroom)),
                # Gate 6 explicitly reserves 50 of 500 daily requests.
                rpd=max(1, math.floor(advertised_rpd * _float(values, "GEMINI_RPD_HEADROOM", 0.9))),
            )
            concurrency = _int(values, "LLM_GEMINI_CONCURRENCY", 1)
            spacing = _float(values, "GEMINI_MIN_REQUEST_SPACING_SECONDS", 5.0)
        else:
            limits = RateLimits(
                rpm=_int(values, f"{upper}_LIMIT_RPM", 60),
                tpm=_int(values, f"{upper}_LIMIT_TPM", 1_000_000),
                rpd=_int(values, f"{upper}_LIMIT_RPD", 1_000),
            )
            concurrency = _int(values, f"LLM_{upper}_CONCURRENCY", 1)
            spacing = _float(values, f"{upper}_MIN_REQUEST_SPACING_SECONDS", 0.0)

        providers.append(
            ProviderConfig(
                name=name,
                keys=keys,
                models=models,
                api_base=values.get(f"{upper}_API_BASE") or DEFAULT_BASES.get(name, ""),
                quota_scope=values.get(f"{upper}_QUOTA_SCOPE") or f"{name}-project-default",
                limits=limits,
                concurrency=concurrency,
                min_spacing_seconds=spacing,
            )
        )

    return RouterConfig(
        providers=tuple(providers),
        enabled=_bool(values, "LLM_ROUTER_ENABLED", False),
        provider_order=order,
        queue_size=_int(values, "LLM_QUEUE_SIZE", 32),
        provider_cooldown_seconds=_float(values, "LLM_PROVIDER_COOLDOWN_SECONDS", 300),
        key_cooldown_seconds=_float(values, "LLM_KEY_COOLDOWN_SECONDS", 60),
        transient_retry_jitter_seconds=_float(values, "LLM_TRANSIENT_RETRY_JITTER_SECONDS", 0.25),
        max_route_attempts=_int(values, "LLM_MAX_ROUTE_ATTEMPTS", 64),
    )
