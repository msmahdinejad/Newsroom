"""One-shot local bootstrap: print sender user ID + private chat ID from one Bot API update.

Reads TELEGRAM_BOT_TOKEN from .env only. Does not:
- show Token
- persist updates/commands
- generate reports
- advance cursors
- enable allow-all production mode

Usage (bot must not be polling elsewhere):
  uv run python scripts/discover_telegram_ids.py
Then message the bot once (any text). Exits after first private message/callback.
"""

from __future__ import annotations

import asyncio
import sys

from newsroom.config import settings
from newsroom.delivery.client import TelegramBotClient, redact_token


async def main() -> int:
    if not settings.telegram_bot_token:
        print("TELEGRAM_BOT_TOKEN not set in .env — abort")
        return 1
    print(f"token configured: true  source: environment  display: {redact_token()}")
    print("Waiting for one private message or callback… (message the bot now)")

    api = TelegramBotClient()
    try:
        me = await api.get_me()
        result = me.get("result") or {}
        print(f"bot_username: @{result.get('username', '?')}")
        print(f"bot_id: {result.get('id', '?')}")
        await api.delete_webhook()
        offset = 0
        while True:
            data = await api.get_updates(offset=offset, timeout=30)
            for update in data.get("result") or []:
                offset = int(update["update_id"]) + 1
                user_id = None
                chat_id = None
                username = None
                if "message" in update:
                    msg = update["message"]
                    user_id = msg.get("from", {}).get("id")
                    username = msg.get("from", {}).get("username")
                    chat = msg.get("chat") or {}
                    if chat.get("type") != "private":
                        continue
                    chat_id = chat.get("id")
                elif "callback_query" in update:
                    cb = update["callback_query"]
                    user_id = cb.get("from", {}).get("id")
                    username = cb.get("from", {}).get("username")
                    chat = (cb.get("message") or {}).get("chat") or {}
                    if chat.get("type") and chat.get("type") != "private":
                        continue
                    chat_id = chat.get("id") or user_id
                else:
                    continue
                if user_id is None or chat_id is None:
                    continue
                print("---")
                print(f"user_id: {user_id}")
                print(f"chat_id: {chat_id}")
                if username:
                    print(f"username: @{username}")
                print("---")
                print("Add to .env:")
                print(f"TELEGRAM_AUTHORIZED_USER_IDS={user_id}")
                print(f"TELEGRAM_CHAT_ID={chat_id}")
                print("TELEGRAM_BOT_ENABLED=true")
                return 0
    finally:
        await api.close()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        raise SystemExit(130) from None
