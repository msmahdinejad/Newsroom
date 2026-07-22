"""Bounded provider-model validation entry point with safe JSON output."""

from __future__ import annotations

import argparse
import json

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
    router = create_router_from_local_env(
        args.env_file,
        state_sink=sink,
        validated_models=restored.validated_model_ids,
        restored_snapshot=restored.snapshots,
        validate_models=False,
        timeout_seconds=max(1.0, min(args.timeout_seconds, 90.0)),
    )
    results = router.validate_models()
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
    print(json.dumps({"models": safe}, ensure_ascii=False, default=str))
    return 0 if any(result.status == "validated" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
