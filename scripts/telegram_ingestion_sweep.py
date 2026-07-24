"""Run one bounded Telegram ingestion cycle and emit only safe aggregate evidence."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from newsroom.sources.telegram_collector import TelegramMTProtoCollector
from newsroom.sources.telegram_ingestor_service import (
    _collect_all_channels,
    _safe_failure_category,
)


async def _run() -> int:
    collector = TelegramMTProtoCollector()
    started_at = datetime.now(UTC)
    try:
        await collector._ensure_client()
        identity = await collector.get_self_identity()
        if not identity:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "failure_category": "authentication_required",
                    },
                    sort_keys=True,
                )
            )
            return 1
        results = await _collect_all_channels(collector)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "failure_category": _safe_failure_category(exc),
                },
                sort_keys=True,
            )
        )
        return 1
    finally:
        await collector.close()

    successful = len(results["channels"])
    failed = len(results["failed"])
    print(
        json.dumps(
            {
                "status": "completed",
                "authenticated": True,
                "transport": collector.transport_label,
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
                "attempted": successful + failed,
                "successful": successful,
                "failed": failed,
                "new": results["collected"],
                "updated": results["updated"],
                "skipped": results["skipped"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
