"""Telegram MTProto ingestor service — live collection loop with reconciliation.

Disabled without credentials (idle, stable, honest health).
Enabled: periodic incremental collection from authorized channels.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from newsroom.logging import get_logger, setup_logging
from newsroom.service_status import telegram_ingestor_status
from newsroom.sources.telegram_collector import TelegramMTProtoCollector
from newsroom.storage.database import get_db
from newsroom.storage.models import Source, TelegramChannel

logger = get_logger(__name__)

_STATUS_FILE = "/tmp/newsroom_ingestor_status.json"
_RECONCILIATION_INTERVAL = 300  # 5 minutes — bounded, not high-frequency
_COLLECTION_LIMIT = 100  # max messages per channel per run


def _write_status(payload: dict) -> None:
    try:
        with open(_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, default=str)
    except OSError:
        pass


def _read_status() -> dict:
    try:
        with open(_STATUS_FILE, encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except Exception:
        return {}


def _deep_health() -> dict:
    """Compute deep health from DB state — not just process existence."""
    payload = telegram_ingestor_status()
    if payload["status"] not in ("enabled",):
        return payload

    try:
        with get_db() as db:
            channels = db.query(TelegramChannel).all()
            total = len(channels)
            healthy = sum(1 for c in channels if c.source_state == "healthy")
            degraded = sum(1 for c in channels if c.source_state in ("degraded", "rate_limited"))
            inaccessible = sum(1 for c in channels if c.source_state in ("inaccessible", "invalid"))
            enabled = sum(1 for c in channels if c.enabled)

            # Check for active FloodWait
            now = datetime.now(UTC)
            floodwait_active = [
                c.public_username or str(c.telegram_channel_id)
                for c in channels
                if c.floodwait_until and c.floodwait_until > now
            ]

            payload["channels_configured"] = total
            payload["channels_enabled"] = enabled
            payload["channels_healthy"] = healthy
            payload["channels_degraded"] = degraded
            payload["channels_inaccessible"] = inaccessible
            payload["floodwait_active"] = floodwait_active

            # Runtime state from last collection
            runtime = _read_status()
            payload["last_update"] = runtime.get("last_update")
            payload["last_reconciliation"] = runtime.get("last_reconciliation")
            payload["last_persisted_message"] = runtime.get("last_persisted_message")
            payload["current_error_category"] = runtime.get("current_error_category")
            payload["authenticated"] = runtime.get("authenticated", False)
            payload["connection_status"] = runtime.get("connection_status", "disconnected")

            degraded_list = []
            if floodwait_active:
                degraded_list.append("floodwait")
            if not payload.get("authenticated"):
                degraded_list.append("authentication-required")
            if payload["channels_inaccessible"] > 0:
                degraded_list.append("inaccessible_channels")
            if degraded_list:
                payload["degraded"] = degraded_list

            payload["healthy"] = len(degraded_list) == 0

    except Exception as e:
        payload["status"] = "error"
        payload["error"] = str(e)[:200]
        payload["healthy"] = False

    return payload


async def _collect_all_channels(collector: TelegramMTProtoCollector) -> dict:
    """Collect from all enabled telegram channels. Failure isolation per channel."""
    results = {"collected": 0, "updated": 0, "skipped": 0, "failed": [], "channels": []}

    with get_db() as db:
        enabled_sources = (
            db.query(Source)
            .filter(Source.type == "telegram", Source.enabled.is_(True))
            .all()
        )

        for source in enabled_sources:
            try:
                items = await collector.collect(source)
                stats = collector.persist_items(db, source, items)

                # Gap detection
                msg_ids = [it.get("message_id", 0) for it in items if it.get("message_id")]
                gaps = collector.detect_gaps(db, source.id, msg_ids)

                results["collected"] += stats["new"]
                results["updated"] += stats["updated"]
                results["skipped"] += stats["skipped"]
                results["channels"].append({
                    "source": source.name,
                    "new": stats["new"],
                    "updated": stats["updated"],
                    "skipped": stats["skipped"],
                    "gaps": len(gaps),
                })
            except Exception as e:
                logger.error(f"Channel {source.name} failed: {e}")
                results["failed"].append(source.name)

    return results


async def _run_ingestor() -> None:
    """Main ingestor loop — periodic collection with reconciliation."""
    status = telegram_ingestor_status()

    if status["status"] != "enabled":
        logger.info(f"Telegram ingestor {status['status']} — idle (no MTProto auth)")
        _write_status({"status": status["status"], "timestamp": datetime.now(UTC).isoformat()})
        while True:
            await asyncio.sleep(3600)
        return

    collector = TelegramMTProtoCollector()
    runtime_status: dict = {
        "status": "enabled",
        "authenticated": False,
        "connection_status": "connecting",
        "timestamp": datetime.now(UTC).isoformat(),
    }

    try:
        await collector._ensure_client()
        identity = await collector.get_self_identity()
        if identity:
            runtime_status["authenticated"] = True
            runtime_status["self_id"] = identity.get("self_id")
            runtime_status["connection_status"] = "connected"
            logger.info(
                f"MTProto authenticated as user {identity.get('self_id')} "
                f"(@{identity.get('username', '?')})"
            )
        else:
            runtime_status["connection_status"] = "auth_failed"
            runtime_status["current_error_category"] = "authentication-required"
            _write_status(runtime_status)
            while True:
                await asyncio.sleep(3600)
            return
    except Exception as e:
        logger.error(f"MTProto connection failed: {e}")
        runtime_status["connection_status"] = "connection_failed"
        runtime_status["current_error_category"] = "connection_error"
        _write_status(runtime_status)
        while True:
            await asyncio.sleep(3600)
        return

    _write_status(runtime_status)

    # Main collection loop
    while True:
        try:
            logger.info("Starting telegram collection cycle")
            results = await _collect_all_channels(collector)

            runtime_status["last_update"] = datetime.now(UTC).isoformat()
            runtime_status["last_reconciliation"] = datetime.now(UTC).isoformat()
            if results["collected"] > 0:
                runtime_status["last_persisted_message"] = datetime.now(UTC).isoformat()

            logger.info(
                f"Collection cycle complete: {results['collected']} new, "
                f"{results['updated']} updated, {results['skipped']} skipped, "
                f"{len(results['failed'])} failed"
            )
            _write_status(runtime_status)

        except Exception as e:
            logger.error(f"Collection cycle error: {e}")
            runtime_status["current_error_category"] = "collection_error"
            _write_status(runtime_status)

        await asyncio.sleep(_RECONCILIATION_INTERVAL)


def main() -> None:
    setup_logging()
    asyncio.run(_run_ingestor())


if __name__ == "__main__":
    main()
