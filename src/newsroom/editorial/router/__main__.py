"""Bounded provider-model validation entry point with safe JSON output."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace

from newsroom.editorial.router.factory import create_router_from_local_env
from newsroom.editorial.router_persistence import PostgresRouterStateSink


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate configured editorial model routes")
    parser.add_argument("validate", nargs="?", default="validate")
    parser.add_argument("--env-file", default=".env.providers.local")
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    args = parser.parse_args()
    sink = PostgresRouterStateSink()
    restored = sink.load()
    # Independent validation must be able to recheck a value after an
    # owner/provider-side correction. Preserve durable quota and circuit state
    # but do not let an old key-local rejection suppress the bounded probe.
    validation_snapshot = replace(restored.snapshots, keys=())
    router = create_router_from_local_env(
        args.env_file,
        state_sink=sink,
        validated_models=restored.validated_model_ids,
        restored_snapshot=validation_snapshot,
        validate_models=False,
        timeout_seconds=max(1.0, min(args.timeout_seconds, 90.0)),
    )
    results = router.validate_models()
    access_results = router.validate_access_values()
    safe = [
        {
            "provider": result.provider,
            "model": result.model,
            "status": result.status,
            "latency_ms": result.latency_ms,
            "failure_category": result.failure_category,
            "supported_capabilities": result.supported_capabilities,
        }
        for result in results
    ]
    safe_access = [
        {
            "provider": result.provider,
            "safe_id": result.safe_id,
            "model": result.model,
            "status": result.status,
            "latency_ms": result.latency_ms,
            "failure_category": result.failure_category,
        }
        for result in access_results
    ]
    print(
        json.dumps(
            {
                "transport": router.health()["transport"],
                "access_values": safe_access,
                "models": safe,
            },
            ensure_ascii=False,
            default=str,
        )
    )
    return 0 if any(result.status == "validated" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
