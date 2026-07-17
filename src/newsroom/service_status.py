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
    """Deep health for Telegram ingestor — more than process existence.

    Disabled mode: healthy with explicit disabled status.
    Enabled mode: checks DB, session, channel states, FloodWait, connection.
    """
    if not settings.telegram_ingestor_enabled:
        return {"status": "disabled", "feature": "telegram_ingestor", "healthy": True}

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
            "healthy": True,  # blocked is a valid mode
        }

    # Enabled — check session file exists
    session_path = settings.telegram_session_path
    session_exists = False
    try:
        import os
        session_exists = os.path.exists(session_path)
    except OSError:
        pass

    payload: dict[str, Any] = {
        "status": "enabled",
        "feature": "telegram_ingestor",
        "session_exists": session_exists,
        "session_path": "[PROTECTED]",  # never expose actual path in reports
    }

    # Read runtime status from ingestor process
    try:
        import json as _json
        with open("/tmp/newsroom_ingestor_status.json", encoding="utf-8") as f:
            runtime = _json.load(f)
        payload["authenticated"] = runtime.get("authenticated", False)
        payload["connection_status"] = runtime.get("connection_status", "disconnected")
        payload["last_update"] = runtime.get("last_update")
        payload["last_reconciliation"] = runtime.get("last_reconciliation")
        payload["last_persisted_message"] = runtime.get("last_persisted_message")
        payload["current_error_category"] = runtime.get("current_error_category")
    except Exception:
        payload["authenticated"] = False
        payload["connection_status"] = "no_runtime_data"

    # Query channel states from DB
    try:
        from newsroom.storage.database import db_health, session_factory
        from newsroom.storage.models import TelegramChannel

        if not db_health():
            payload["degraded"] = ["database"]
            payload["healthy"] = False
            return payload

        with session_factory() as db:
            channels = db.query(TelegramChannel).all()
            payload["channels_configured"] = len(channels)
            payload["channels_enabled"] = sum(1 for c in channels if c.enabled)
            payload["channels_healthy"] = sum(1 for c in channels if c.source_state == "healthy")
            payload["channels_degraded"] = sum(1 for c in channels if c.source_state in ("degraded", "rate_limited"))
            payload["channels_inaccessible"] = sum(1 for c in channels if c.source_state in ("inaccessible", "invalid"))

            from datetime import UTC, datetime
            now = datetime.now(UTC)
            floodwait = [
                c.public_username or str(c.telegram_channel_id)
                for c in channels
                if c.floodwait_until and c.floodwait_until > now
            ]
            if floodwait:
                payload["floodwait_active"] = floodwait
    except Exception:
        payload["channels_configured"] = 0

    degraded = []
    if not payload.get("authenticated"):
        degraded.append("authentication-required")
    if not payload.get("session_exists"):
        degraded.append("session_missing")
    if payload.get("channels_inaccessible", 0) > 0:
        degraded.append("inaccessible_channels")
    if payload.get("floodwait_active"):
        degraded.append("floodwait")
    if degraded:
        payload["degraded"] = degraded
    payload["healthy"] = len(degraded) == 0
    return payload


def collector_status() -> dict[str, Any]:
    if not db_health():
        return {"status": "unhealthy", "reason": "database"}
    return {"status": "healthy", "role": "collector"}


def report_worker_status() -> dict[str, Any]:
    if not db_health():
        return {"status": "unhealthy", "reason": "database"}
    return {"status": "healthy", "role": "report_worker"}


def editorial_status() -> dict[str, Any]:
    """Editorial health — no secrets exposed."""
    if not db_health():
        return {"status": "disabled", "feature": "editorial", "healthy": True}

    try:
        from sqlalchemy.orm import sessionmaker

        from newsroom.editorial.persistence import get_editorial_health
        from newsroom.storage.database import engine

        factory = sessionmaker(bind=engine)
        with factory() as db:
            return get_editorial_health(db)
    except Exception as e:
        return {
            "status": "disabled" if not settings.editorial_enabled else "degraded",
            "feature": "editorial",
            "healthy": True,  # editorial failure never marks stack unhealthy
            "error": str(e)[:100],
        }


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
    elif kind == "editorial":
        payload = editorial_status()
        ok = payload.get("healthy", True)
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
