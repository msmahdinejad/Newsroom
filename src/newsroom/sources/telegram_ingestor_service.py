"""Dedicated Telegram MTProto ingestion owner with bounded recovery.

The production collector service never mounts the MTProto session. This
service alone connects the user session, onboards public channel identities,
persists per-source attempts/cursors, and retries a failed transport only
after a bounded cooldown.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlparse

from newsroom.config import settings
from newsroom.logging import get_logger, setup_logging
from newsroom.pipeline.cursors import advance_cursor_from_items, load_cursor, save_cursor
from newsroom.service_status import telegram_ingestor_status
from newsroom.sources.base import CollectionError
from newsroom.sources.telegram_collector import TelegramMTProtoCollector
from newsroom.storage.database import get_db
from newsroom.storage.models import CollectionRun, Source, TelegramChannel

logger = get_logger(__name__)

_STATUS_FILE = "/tmp/newsroom_ingestor_status.json"
_RECONCILIATION_INTERVAL = 300


def _write_status(payload: dict[str, Any]) -> None:
    """Write safe runtime state; never include identity/session/proxy values."""
    try:
        with open(_STATUS_FILE, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, default=str)
    except OSError:
        pass


def _read_status() -> dict[str, Any]:
    try:
        with open(_STATUS_FILE, encoding="utf-8") as file:
            value = json.load(file)
            return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _deep_health() -> dict[str, Any]:
    """Compute deep health from DB and safe runtime state."""
    payload = telegram_ingestor_status()
    if payload["status"] != "enabled":
        return payload

    try:
        with get_db() as db:
            channels = db.query(TelegramChannel).all()
            payload["channels_configured"] = len(channels)
            payload["channels_enabled"] = sum(1 for channel in channels if channel.enabled)
            payload["channels_healthy"] = sum(
                1 for channel in channels if channel.source_state == "healthy"
            )
            payload["channels_degraded"] = sum(
                1
                for channel in channels
                if channel.source_state in ("degraded", "rate_limited")
            )
            payload["channels_inaccessible"] = sum(
                1
                for channel in channels
                if channel.source_state in ("inaccessible", "invalid")
            )
            now = datetime.now(UTC)
            payload["floodwait_count"] = sum(
                1
                for channel in channels
                if channel.floodwait_until and channel.floodwait_until > now
            )
            payload.update(
                {
                    key: value
                    for key, value in _read_status().items()
                    if key
                    in {
                        "authenticated",
                        "connection_status",
                        "transport",
                        "last_update",
                        "last_reconciliation",
                        "last_persisted_message",
                        "current_error_category",
                        "sources_attempted",
                    }
                }
            )
    except Exception:
        payload["healthy"] = False
        payload["degraded"] = ["database"]
    return payload


def _channel_handle(source: Source) -> str:
    configured = str((source.config or {}).get("channel_username") or "").strip()
    if configured:
        return configured.lstrip("@").split("/")[-1]
    raw = (source.url or "").strip()
    if raw.startswith("@"):
        return raw[1:]
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    parts = [part for part in parsed.path.split("/") if part]
    if parts and parts[0].lower() == "s" and len(parts) > 1:
        return parts[1]
    return parts[0] if parts else ""


async def _ensure_channel(
    db: Any,
    collector: TelegramMTProtoCollector,
    source: Source,
) -> TelegramChannel:
    existing = cast(
        TelegramChannel | None,
        db.query(TelegramChannel).filter_by(source_id=source.id).first(),
    )
    if existing is not None:
        if not (source.config or {}).get("channel_username"):
            config = dict(source.config or {})
            config["channel_username"] = existing.public_username or _channel_handle(source)
            config["telegram_channel_id"] = existing.telegram_channel_id
            source.config = config
        existing.enabled = bool(source.enabled)
        return existing

    handle = _channel_handle(source)
    if not handle:
        raise CollectionError("telegram_handle_missing", source.url, recoverable=False)
    if type(db).__module__.startswith("sqlalchemy."):
        db.commit()
    resolved = await collector.resolve_channel(handle)
    if resolved is None:
        raise CollectionError("telegram_channel_unresolvable", source.url, recoverable=False)

    duplicate = (
        db.query(TelegramChannel)
        .filter_by(telegram_channel_id=resolved["telegram_channel_id"])
        .first()
    )
    if duplicate is not None and duplicate.source_id != source.id:
        raise CollectionError("telegram_duplicate_identity", source.url, recoverable=False)

    channel = TelegramChannel(
        source_id=source.id,
        telegram_channel_id=resolved["telegram_channel_id"],
        access_hash=resolved["access_hash"],
        public_username=resolved["public_username"],
        public_url=resolved["public_url"],
        display_name=resolved["display_name"],
        language=source.language,
        category=source.category,
        trust_class=source.trust_class,
        source_state="configured",
        enabled=True,
    )
    db.add(channel)
    config = dict(source.config or {})
    config["channel_username"] = resolved["public_username"] or handle
    config["telegram_channel_id"] = resolved["telegram_channel_id"]
    source.config = config
    db.flush()
    return channel


def _safe_failure_category(exc: Exception) -> str:
    text = str(exc).lower()
    if "floodwait" in text:
        return "floodwait"
    if "private" in text:
        return "channel_private"
    if "unresolvable" in text or "not occupied" in text:
        return "channel_unresolvable"
    if "handle_missing" in text:
        return "handle_missing"
    if "auth" in text or "unauthorized" in text:
        return "authentication_required"
    if "timeout" in text:
        return "connection_timeout"
    if "connect" in text:
        return "connection_error"
    return "collection_error"


def _source_activity(source: Source) -> tuple[datetime, int]:
    stamps = [
        stamp
        for stamp in (source.last_attempt_at, source.last_success_at, source.last_error_at)
        if stamp
    ]
    return (max(stamps, default=datetime.min.replace(tzinfo=UTC)), source.id)


async def _collect_all_channels(collector: TelegramMTProtoCollector) -> dict[str, Any]:
    """Collect a least-recently-attempted bounded batch with failure isolation."""
    results: dict[str, Any] = {
        "collected": 0,
        "updated": 0,
        "skipped": 0,
        "failed": [],
        "channels": [],
    }
    with get_db() as db:
        sources = (
            db.query(Source)
            .filter(Source.type == "telegram", Source.enabled.is_(True))
            .all()
        )
        sources.sort(key=_source_activity)
        sources = sources[: max(1, settings.telegram_max_sources_per_cycle)]

        for index, source in enumerate(sources):
            attempt_at = datetime.now(UTC)
            source.last_attempt_at = attempt_at
            source.validation_status = "attempting"
            source.failure_category = None
            run = CollectionRun(source_id=source.id, started_at=attempt_at, status="running")
            db.add(run)
            db.flush()
            run_id = int(run.id)
            if type(db).__module__.startswith("sqlalchemy."):
                # Persist the attempt boundary before any MTProto I/O.
                db.commit()
            try:
                channel = await _ensure_channel(db, collector, source)
                items = await collector.collect(source)
                if type(db).__module__.startswith("sqlalchemy."):
                    source = db.merge(source)
                stats = collector.persist_items(db, source, items)
                message_ids = [item.get("message_id", 0) for item in items if item.get("message_id")]
                gaps = collector.detect_gaps(db, source.id, message_ids)

                cursor = load_cursor(db, source.id)
                next_cursor = advance_cursor_from_items(cursor, items, source_type="telegram")
                if not items:
                    next_cursor = dict(cursor)
                    next_cursor.setdefault("last_message_id", str(channel.last_message_id or 0))
                    next_cursor["updated_at"] = datetime.now(UTC).isoformat()
                save_cursor(db, source.id, next_cursor)

                source.last_success_at = datetime.now(UTC)
                source.last_error = None
                source.consecutive_failures = 0
                source.health_status = "healthy"
                source.validation_status = "valid"
                source.failure_category = None
                source.no_cursor_reason = None
                run.status = "ok"
                run.items_collected = stats["new"]
                run.finished_at = datetime.now(UTC)
                results["collected"] += stats["new"]
                results["updated"] += stats["updated"]
                results["skipped"] += stats["skipped"]
                results["channels"].append(
                    {
                        "source_id": source.id,
                        "new": stats["new"],
                        "updated": stats["updated"],
                        "skipped": stats["skipped"],
                        "gaps": len(gaps),
                    }
                )
            except Exception as exc:
                if type(db).__module__.startswith("sqlalchemy."):
                    source = db.merge(source)
                    persisted_run = db.get(CollectionRun, run_id)
                    if persisted_run is not None:
                        run = persisted_run
                category = _safe_failure_category(exc)
                logger.error(
                    "Telegram channel collection failed",
                    extra={"failure_category": category, "source_id": source.id},
                )
                source.last_error_at = datetime.now(UTC)
                source.last_error = category
                source.consecutive_failures = (source.consecutive_failures or 0) + 1
                source.validation_status = "failed"
                source.failure_category = category
                source.no_cursor_reason = "mtproto_connection_failed"
                if source.consecutive_failures >= 3:
                    source.health_status = "degraded"
                run.status = "error"
                run.error = category
                run.finished_at = datetime.now(UTC)
                results["failed"].append(source.id)

            if type(db).__module__.startswith("sqlalchemy."):
                db.commit()

            if index + 1 < len(sources) and settings.telegram_source_spacing_seconds > 0:
                await asyncio.sleep(settings.telegram_source_spacing_seconds)
    return results


def _record_global_connection_failure(category: str) -> int:
    """Persist one safe bounded attempt for every configured Telegram source."""
    attempted = 0
    with get_db() as db:
        sources = (
            db.query(Source)
            .filter(Source.type == "telegram", Source.enabled.is_(True))
            .all()
        )
        now = datetime.now(UTC)
        for source in sources:
            db.add(
                CollectionRun(
                    source_id=source.id,
                    started_at=now,
                    finished_at=now,
                    status="error",
                    items_collected=0,
                    error=category,
                )
            )
            source.last_error_at = now
            source.last_attempt_at = now
            source.last_error = category
            source.consecutive_failures = (source.consecutive_failures or 0) + 1
            source.validation_status = "failed"
            source.failure_category = category
            source.no_cursor_reason = "mtproto_connection_failed"
            if source.consecutive_failures >= 3:
                source.health_status = "degraded"
            attempted += 1
    return attempted


async def _run_ingestor() -> None:
    status = telegram_ingestor_status()
    if status["status"] != "enabled":
        logger.info("Telegram ingestor unavailable; idling", extra={"status": status["status"]})
        _write_status(
            {
                "status": status["status"],
                "authenticated": False,
                "connection_status": status["status"],
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        while True:
            await asyncio.sleep(3600)

    collector = TelegramMTProtoCollector()
    runtime: dict[str, Any] = {"status": "enabled", "authenticated": None}
    while True:
        try:
            runtime.update(
                {
                    "connection_status": "connecting",
                    "transport": collector.transport_label,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            _write_status(runtime)
            await collector._ensure_client()
            identity = await collector.get_self_identity()
            if not identity:
                raise CollectionError("MTProto session is not authorized", "", recoverable=False)

            runtime.update(
                {
                    "authenticated": True,
                    "connection_status": "connected",
                    "transport": collector.transport_label,
                    "current_error_category": None,
                }
            )
            logger.info("MTProto authenticated", extra={"transport": collector.transport_label})
            _write_status(runtime)

            results = await _collect_all_channels(collector)
            now = datetime.now(UTC).isoformat()
            runtime["last_update"] = now
            runtime["last_reconciliation"] = now
            runtime["sources_attempted"] = len(results["channels"]) + len(results["failed"])
            if results["collected"] > 0:
                runtime["last_persisted_message"] = now
            logger.info(
                "Telegram collection cycle complete",
                extra={
                    "new": results["collected"],
                    "updated": results["updated"],
                    "skipped": results["skipped"],
                    "failed_count": len(results["failed"]),
                },
            )
            _write_status(runtime)
        except Exception as exc:
            category = _safe_failure_category(exc)
            logger.error("MTProto cycle failed", extra={"failure_category": category})
            runtime.update(
                {
                    "connection_status": "connection_failed",
                    "current_error_category": category,
                    "sources_attempted": _record_global_connection_failure(category),
                }
            )
            if category == "authentication_required":
                runtime["authenticated"] = False
            _write_status(runtime)
            await collector.close()
            await asyncio.sleep(max(1, settings.telegram_reconnect_cooldown_seconds))
            continue

        await asyncio.sleep(_RECONCILIATION_INTERVAL)


def main() -> None:
    setup_logging()
    asyncio.run(_run_ingestor())


if __name__ == "__main__":
    main()
