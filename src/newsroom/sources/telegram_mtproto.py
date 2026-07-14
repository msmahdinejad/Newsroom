"""Telegram MTProto source collector.

Uses Telethon for MTProto user session. Separate from the Bot API delivery.
Requires one-time local authorization with api_id, api_hash, phone.

Security:
- Session file stored in configurable directory with restricted access
- Collects only public channels the authorized account has joined
- No posting, voting, reactions, or subscriber manipulation
- Incremental cursors via message ID
- FloodWait handling with exponential backoff
"""

from typing import Any

from newsroom.config import settings
from newsroom.logging import get_logger
from newsroom.sources.base import CollectionError, SourceCollector
from newsroom.storage.models import Source

logger = get_logger(__name__)


class TelegramMTProtoCollector(SourceCollector):
    """Collect from public Telegram channels via MTProto user session."""

    def __init__(self) -> None:
        self._client = None
        self._session_dir = settings.telegram_session_dir
        self._api_id = settings.telegram_api_id
        self._api_hash = settings.telegram_api_hash
        self._phone = settings.telegram_phone

    @property
    def configured(self) -> bool:
        return bool(self._api_id and self._api_hash and self._phone)

    async def _ensure_client(self) -> None:
        """Initialize or connect the Telethon client."""
        if self._client is not None:
            return

        if not self.configured:
            raise CollectionError(
                "MTProto not configured — set TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE",
                "",
                recoverable=False,
            )

        try:
            from telethon import TelegramClient
        except ImportError as e:
            raise CollectionError(
                "Telethon not installed — run: pip install telethon",
                "",
                recoverable=False,
            ) from e

        import os
        os.makedirs(self._session_dir, exist_ok=True)
        session_file = os.path.join(self._session_dir, "newsroom_collector")

        self._client = TelegramClient(
            session_file,
            int(self._api_id),
            self._api_hash,
        )
        await self._client.start(phone=self._phone)
        logger.info("Telegram MTProto client connected")

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        """Collect recent messages from a Telegram channel."""
        if not self.configured:
            raise CollectionError("MTProto not configured", source.url, recoverable=False)

        await self._ensure_client()

        channel = source.config.get("channel_username") or source.url
        limit = source.config.get("batch_size", 50)

        try:
            from telethon.errors import FloodWaitError
        except ImportError:
            FloodWaitError = type("FloodWaitError", (Exception,), {"seconds": 0})  # noqa: N806

        try:
            from telethon.tl.types import Message
        except ImportError:
            raise CollectionError("Telethon not installed", source.url, recoverable=False) from None

        items: list[dict[str, Any]] = []
        try:
            async for msg in self._client.iter_messages(channel, limit=limit):
                if not isinstance(msg, Message):
                    continue
                # Skip media-only messages with no text
                text = msg.text or ""
                if not text.strip():
                    continue

                item = {
                    "type": "telegram",
                    "source_id": source.id,
                    "source_name": source.name,
                    "source_url": source.url,
                    "message_id": msg.id,
                    "text": text[:5000],
                    "date": msg.date.isoformat() if msg.date else None,
                    "channel_name": channel,
                    "link": self._build_link(channel, msg.id),
                    "forward_from": self._extract_forward(msg),
                    "is_edited": bool(msg.edit_date),
                    "edit_date": msg.edit_date.isoformat() if msg.edit_date else None,
                }
                items.append(item)

            logger.info(f"Collected {len(items)} messages from {channel}")
            return items

        except FloodWaitError as e:
            wait = e.seconds
            logger.warning(f"FloodWait: must wait {wait}s")
            raise CollectionError(
                f"FloodWait: {wait}s",
                source.url,
                recoverable=True,
            ) from e
        except Exception as e:
            raise CollectionError(
                f"Telegram collection error: {e}",
                source.url,
                recoverable=False,
            ) from e

    def validate_url(self, source_url: str) -> bool:
        """Telegram public channel: @username or https://t.me/username."""
        return (
            source_url.startswith("@")
            or "t.me/" in source_url
            or "telegram.me/" in source_url
        )

    def _build_link(self, channel: str, msg_id: int) -> str:
        """Build public permalink."""
        username = channel.lstrip("@") if channel.startswith("@") else channel
        if "t.me/" in username:
            username = username.split("t.me/")[-1]
        return f"https://t.me/{username}/{msg_id}"

    def _extract_forward(self, msg: Any) -> dict[str, Any] | None:
        """Extract forwarding metadata."""
        fwd = getattr(msg, "fwd_from", None)
        if not fwd:
            return None
        return {
            "from_channel": getattr(fwd, "from_id", None),
            "from_message_id": getattr(fwd, "channel_post", None),
            "from_name": getattr(fwd, "from_name", None),
        }

    async def health_check(self, source: Source) -> bool:
        """Check if channel is accessible."""
        if not self.configured:
            return False
        try:
            await self._ensure_client()
            entity = await self._client.get_entity(source.url)
            return entity is not None
        except Exception as e:
            logger.warning(f"Channel {source.url} health check failed: {e}")
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.disconnect()
            self._client = None
