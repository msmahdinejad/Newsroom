"""Bounded, non-destructive Telegram MTProto transport diagnosis.

The probe reuses the existing session without deleting or regenerating it and
prints only transport mode, safe outcome category, and authorization state.
It must run while the production ingestor is stopped so the SQLite session has
exactly one owner.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.network.connection.tcpabridged import ConnectionTcpAbridged
from telethon.network.connection.tcpfull import ConnectionTcpFull
from telethon.network.connection.tcpintermediate import ConnectionTcpIntermediate
from telethon.network.connection.tcpobfuscated import ConnectionTcpObfuscated

from newsroom.config import settings

MODES: dict[str, type] = {
    "abridged": ConnectionTcpAbridged,
    "intermediate": ConnectionTcpIntermediate,
    "full": ConnectionTcpFull,
    "obfuscated": ConnectionTcpObfuscated,
}


def _safe_category(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "connection_timeout"
    if isinstance(exc, OSError):
        if exc.errno in {51, 65, 10051, 101, 113}:
            return "network_unreachable"
        if exc.errno in {61, 10061, 111}:
            return "connection_refused"
        return "network_error"
    return "mtproto_handshake_failed"


async def _probe(mode: str, connection: type) -> dict[str, Any]:
    client = TelegramClient(
        settings.telegram_session_path,
        int(settings.telegram_api_id),
        settings.telegram_api_hash,
        connection=connection,
        timeout=8,
        connection_retries=0,
        request_retries=0,
        retry_delay=1,
        auto_reconnect=False,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=12)
        authorized = await asyncio.wait_for(client.is_user_authorized(), timeout=8)
        return {
            "mode": mode,
            "status": "connected",
            "authenticated": bool(authorized),
        }
    except BaseException as exc:
        return {
            "mode": mode,
            "status": "failed",
            "failure_category": _safe_category(exc),
            "authenticated": None,
        }
    finally:
        if client.is_connected():
            await client.disconnect()


async def probe_all(names: Sequence[str] | None = None) -> list[dict[str, Any]]:
    selected = names or tuple(MODES)
    return [await _probe(name, MODES[name]) for name in selected]


def main() -> int:
    session = Path(settings.telegram_session_path)
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        print(json.dumps({"status": "unavailable", "reason": "credentials_not_configured"}))
        return 2
    if not session.exists():
        print(json.dumps({"status": "unavailable", "reason": "session_not_found"}))
        return 2
    results = asyncio.run(probe_all())
    print(json.dumps({"transports": results}, sort_keys=True))
    return 0 if any(result["status"] == "connected" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
