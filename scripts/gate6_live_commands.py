"""Gate 6 live Telegram command verification.

Calls the bot command handlers with the REAL Bot API client and the real
authorized chat, delivering /status /sources /schedule messages to Telegram.
Confirms the commands work end-to-end (handler + Bot API delivery) and the
message IDs are returned. Does not print tokens or personal identifiers.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# ruff: noqa: E402
from newsroom.delivery.bot import TelegramBot  # noqa: E402
from newsroom.delivery.status_commands import schedule_text, sources_text, status_text  # noqa: E402
from newsroom.storage.database import get_db  # noqa: E402


async def main() -> int:
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat:
        print("no TELEGRAM_CHAT_ID set — skipping live command test")
        return 1
    bot = TelegramBot()
    results = {}
    with get_db() as db:
        for name, text in [
            ("/status", status_text(db)),
            ("/sources", sources_text(db)),
            ("/schedule", schedule_text(db)),
        ]:
            try:
                resp = await bot.api.send_message(chat, text)
                ok = resp.get("ok")
                msg_id = resp.get("result", {}).get("message_id")
                results[name] = {"ok": ok, "message_id": msg_id}
                print(f"{name}: ok={ok} message_id={msg_id}")
            except Exception as e:
                results[name] = {"ok": False, "error": str(e)[:120]}
                print(f"{name}: ERROR {e!s:.120}")
    await bot.api.close()
    return 0 if all(r.get("ok") for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
