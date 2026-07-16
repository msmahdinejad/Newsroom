"""Service status helpers for healthchecks (disabled vs failed)."""

from __future__ import annotations

import json
import sys
from typing import Any

from newsroom.config import settings
from newsroom.storage.database import db_health


def telegram_bot_status() -> dict[str, Any]:
    """Deep health for Telegram bot — more than process existence.

    Disabled mode: healthy with explicit disabled status.
    Enabled mode: checks DB, allowlist, polling, identity, last update/delivery.
    """
    if not settings.telegram_bot_enabled:
        return {"status": "disabled", "feature": "telegram_bot", "healthy": True}

    if not settings.telegram_bot_token:
        return {
            "status": "blocked_by_credentials",
            "feature": "telegram_bot",
            "missing": "TELEGRAM_BOT_TOKEN",
            "healthy": True,  # Gate 1: blocked is a valid mode
        }

    # Enabled — deep health
    payload: dict[str, Any] = {"status": "enabled", "feature": "telegram_bot"}
    payload["db_connected"] = db_health()
    allowed = settings.authorized_user_ids()
    payload["authorized_users_count"] = len(allowed)

    degraded = []
    if not payload["db_connected"]:
        degraded.append("database")
    if not allowed:
        degraded.append("empty_allowlist")

    # Read runtime status file if available (written by bot process)
    try:
        import json as _json

        with open("/tmp/newsroom_bot_status.json", encoding="utf-8") as f:
            runtime = _json.load(f)
        payload["polling_alive"] = runtime.get("polling_alive", False)
        payload["last_update"] = runtime.get("last_update")
        payload["last_delivery"] = runtime.get("last_delivery")
        payload["bot_username"] = runtime.get("bot_username")
        if runtime.get("degraded"):
            degraded.extend(runtime["degraded"])
    except Exception:
        payload["polling_alive"] = False

    if degraded:
        payload["degraded"] = degraded
    payload["healthy"] = len(degraded) == 0
    return payload


def telegram_ingestor_status() -> dict[str, Any]:
    if not settings.telegram_ingestor_enabled:
        return {"status": "disabled", "feature": "telegram_ingestor"}
    missing = []
    if not settings.telegram_api_id:
        missing.append("TELEGRAM_API_ID")
    if not settings.telegram_api_hash:
        missing.append("TELEGRAM_API_HASH")
    if not settings.telegram_phone:
        missing.append("TELEGRAM_PHONE")
    if missing:
        return {
            "status": "blocked_by_credentials",
            "feature": "telegram_ingestor",
            "missing": missing,
        }
    return {"status": "enabled", "feature": "telegram_ingestor"}


def collector_status() -> dict[str, Any]:
    if not db_health():
        return {"status": "unhealthy", "reason": "database"}
    return {"status": "healthy", "role": "collector"}


def report_worker_status() -> dict[str, Any]:
    if not db_health():
        return {"status": "unhealthy", "reason": "database"}
    return {"status": "healthy", "role": "report_worker"}


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m newsroom.service_status <bot|ingestor|collector|scheduler|db>"""
    argv = argv or sys.argv[1:]
    kind = argv[0] if argv else "db"
    if kind == "bot":
        payload = telegram_bot_status()
        # disabled/blocked are healthy modes; enabled checks deep health
        ok = payload.get("healthy", False)
    elif kind == "ingestor":
        payload = telegram_ingestor_status()
        ok = payload["status"] in ("disabled", "blocked_by_credentials", "enabled")
    elif kind == "collector":
        payload = collector_status()
        ok = payload["status"] == "healthy"
    elif kind == "report_worker":
        payload = report_worker_status()
        ok = payload["status"] == "healthy"
    elif kind == "scheduler":
        from newsroom.scheduler import health_payload

        payload = health_payload()
        ok = payload["status"] in ("healthy", "starting")
    elif kind == "db":
        ok = db_health()
        payload = {"status": "healthy" if ok else "unhealthy"}
    else:
        payload = {"status": "unknown", "kind": kind}
        ok = False
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
