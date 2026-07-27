"""Safe operator commands for editorial provider validation and health."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, replace

from newsroom.editorial.router.config import load_router_config
from newsroom.editorial.router.factory import create_router_from_local_env
from newsroom.editorial.router_persistence import PostgresRouterStateSink
from newsroom.storage.database import get_db
from newsroom.storage.models import ProviderKeyState, ProviderModelHealth


def providers_command(args: argparse.Namespace) -> int:
    """Dispatch provider commands without exposing access values."""
    if args.providers_command == "validate":
        return _validate(args)
    if args.providers_command == "status":
        return _status()
    print("FAIL: a provider subcommand is required")
    return 2


def _validate(args: argparse.Namespace) -> int:
    provider_file = os.environ.get(
        "LLM_PROVIDER_ENV_FILE",
        ".env.providers.local",
    )
    sink = PostgresRouterStateSink()
    restored = sink.load()
    validation_snapshot = replace(restored.snapshots, keys=())
    router = create_router_from_local_env(
        provider_file,
        state_sink=sink,
        validated_models=restored.validated_model_ids,
        restored_snapshot=validation_snapshot,
    )
    model_filter = tuple(
        value.strip()
        for value in (args.model or ())
        if value.strip()
    )
    model_results = router.validate_models(
        provider=args.provider,
        models=model_filter,
    )
    key_results = router.validate_access_values() if args.validate_keys else []
    payload = {
        "models": [asdict(result) for result in model_results],
        "keys": [asdict(result) for result in key_results],
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if any(result.status == "validated" for result in model_results) else 1


def _status() -> int:
    provider_file = os.environ.get(
        "LLM_PROVIDER_ENV_FILE",
        ".env.providers.local",
    )
    config = load_router_config(provider_file)
    configured_fingerprints = {
        provider.name: {
            hashlib.sha256(value.encode("utf-8")).hexdigest()
            for value in provider.keys
        }
        for provider in config.providers
    }
    with get_db() as db:
        model_rows = (
            db.query(ProviderModelHealth)
            .order_by(ProviderModelHealth.provider, ProviderModelHealth.model)
            .all()
        )
        models = [
            {
                "provider": row.provider,
                "model": row.model,
                "status": row.validation_status,
                "enabled": row.enabled,
                "latency_ms": row.latency_ms,
                "last_success_at": row.last_success_at,
                "last_failure_category": row.last_failure_category,
                "capabilities": row.supported_capabilities,
            }
            for row in model_rows
        ]
        key_rows = (
            db.query(
                ProviderKeyState.provider,
                ProviderKeyState.key_fingerprint,
                ProviderKeyState.enabled,
            )
            .all()
        )
        persisted_enabled = {
            (provider, fingerprint): bool(enabled)
            for provider, fingerprint, enabled in key_rows
        }
        key_counts = {
            provider: {
                "configured": len(fingerprints),
                "enabled": sum(
                    persisted_enabled.get((provider, fingerprint), True)
                    for fingerprint in fingerprints
                ),
            }
            for provider, fingerprints in configured_fingerprints.items()
        }
    payload = {
        "models": models,
        "key_counts": key_counts,
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2, default=str))
    return 0
