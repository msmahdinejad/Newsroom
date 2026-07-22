"""Telegram MTProto collector — channel resolution, incremental collection,
edits, forwards, deletes, FloodWait, gap detection, reconciliation.

Uses Telethon for MTProto user session. Separate from Bot API delivery.
The adapter boundary (telegram_adapter.py) isolates Telethon types from
the rest of the application.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlparse

from sqlalchemy.orm import Session

from newsroom.config import settings
from newsroom.logging import get_logger
from newsroom.sources.base import CollectionError, SourceCollector
from newsroom.sources.telegram_adapter import (
    adapt_telethon_message,
)
from newsroom.storage.models import (
    RawItem,
    Source,
    TelegramChannel,
    TelegramMessageGap,
)

logger = get_logger(__name__)


def telegram_transport_config() -> tuple[dict[str, Any], str]:
    """Return bounded Telethon transport kwargs and a safe transport label.

    Proxy endpoints and credentials are read only from local environment-backed
    settings and are never returned in health output or persisted. MTProxy takes
    precedence over a generic SOCKS/HTTP proxy when both are configured.
    """
    mt_host = settings.telegram_mtproxy_host.strip()
    mt_secret = settings.telegram_mtproxy_secret.strip()
    mt_port = int(settings.telegram_mtproxy_port or 0)
    if mt_host or mt_secret or mt_port:
        if not (mt_host and mt_secret and 1 <= mt_port <= 65535):
            raise CollectionError(
                "MTProxy configuration is incomplete",
                "",
                recoverable=False,
            )
        from telethon.network.connection.tcpmtproxy import (
            ConnectionTcpMTProxyRandomizedIntermediate,
        )

        return {
            "connection": ConnectionTcpMTProxyRandomizedIntermediate,
            "proxy": (mt_host, mt_port, mt_secret),
        }, "mtproxy"

    proxy_url = settings.telegram_proxy_url.strip()
    if not proxy_url:
        return {}, "direct"

    parsed = urlparse(proxy_url)
    if parsed.scheme.lower() not in {"socks5", "socks4", "http"}:
        raise CollectionError("unsupported Telegram proxy scheme", "", recoverable=False)
    if not parsed.hostname or not parsed.port:
        raise CollectionError("Telegram proxy host/port missing", "", recoverable=False)
    try:
        import socks
    except ImportError as exc:
        raise CollectionError("PySocks is required for Telegram proxy", "", recoverable=False) from exc

    proxy_types = {
        "socks5": socks.SOCKS5,
        "socks4": socks.SOCKS4,
        "http": socks.HTTP,
    }
    return {
        "proxy": (
            proxy_types[parsed.scheme.lower()],
            parsed.hostname,
            parsed.port,
            True,
            unquote(parsed.username or ""),
            unquote(parsed.password or ""),
        )
    }, parsed.scheme.lower()


class TelegramMTProtoCollector(SourceCollector):
    """Collect from public Telegram channels via MTProto user session.

    Identity separation:
    - Uses a separate user-account session (TELEGRAM_SESSION_PATH)
    - Never uses the Bot API token
    - Read-only: no posting, voting, reactions, or manipulation
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._session_path = settings.telegram_session_path
        self._api_id = settings.telegram_api_id
        self._api_hash = settings.telegram_api_hash
        self._phone = settings.telegram_phone
        self._transport_label = "direct"

    @property
    def configured(self) -> bool:
        return bool(self._api_id and self._api_hash and self._phone)

    @property
    def transport_label(self) -> str:
        """Safe transport name; never includes an endpoint or credential."""
        return self._transport_label

    async def _ensure_client(self) -> None:
        """Initialize or connect the Telethon client."""
        if self._client is not None:
            is_connected = getattr(self._client, "is_connected", None)
            if not callable(is_connected) or is_connected():
                return
            with contextlib.suppress(Exception):
                await self._client.disconnect()
            self._client = None
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
                "Telethon not installed — run: uv sync --extra telegram",
                "",
                recoverable=False,
            ) from e

        session_dir = os.path.dirname(self._session_path)
        if session_dir:
            os.makedirs(session_dir, exist_ok=True)

        transport, self._transport_label = telegram_transport_config()
        self._client = TelegramClient(
            self._session_path,
            int(self._api_id),
            self._api_hash,
            timeout=max(1, int(settings.telegram_connect_timeout_seconds)),
            connection_retries=max(0, int(settings.telegram_connection_retries)),
            retry_delay=max(0, int(settings.telegram_retry_delay_seconds)),
            auto_reconnect=True,
            **transport,
        )
        connect_deadline = max(5, int(settings.telegram_connect_timeout_seconds)) * (
            max(0, int(settings.telegram_connection_retries)) + 1
        ) + 5
        try:
            await asyncio.wait_for(self._client.connect(), timeout=connect_deadline)
        except Exception as exc:
            with contextlib.suppress(Exception):
                await self._client.disconnect()
            self._client = None
            category = "connect_timeout" if isinstance(exc, TimeoutError) else "connect_failed"
            raise CollectionError(
                f"MTProto {category} ({type(exc).__name__})",
                "",
                recoverable=True,
            ) from exc
        if not await self._client.is_user_authorized():
            raise CollectionError(
                "MTProto session not authorized — run: newsroom authorize-telegram",
                "",
                recoverable=False,
            )
        logger.info("Telegram MTProto client connected")

    async def resolve_channel(self, username: str) -> dict[str, Any] | None:
        """Resolve a public username to a stable channel entity.

        Returns dict with: telegram_channel_id, access_hash, public_username,
        display_name, public_url. Returns None if channel not found.
        """
        await self._ensure_client()
        clean = username.lstrip("@")
        if "t.me/" in clean:
            clean = clean.split("t.me/")[-1]
        try:
            entity = await self._client.get_entity(clean)
        except Exception as e:
            logger.warning(f"Channel resolution failed for @{clean}: {e}")
            return None

        channel_id = getattr(entity, "id", None)
        if channel_id is None:
            return None

        access_hash = getattr(entity, "access_hash", None)
        entity_username = getattr(entity, "username", None)
        display_name = getattr(entity, "title", None) or getattr(entity, "first_name", None) or clean

        return {
            "telegram_channel_id": int(channel_id),
            "access_hash": int(access_hash) if access_hash else None,
            "public_username": entity_username,
            "display_name": str(display_name),
            "public_url": f"https://t.me/{entity_username}" if entity_username else "",
        }

    async def upsert_channel(
        self,
        session: Session,
        username: str,
        *,
        language: str = "en",
        category: str = "general",
        trust_class: str = "unverified",
    ) -> TelegramChannel | None:
        """Resolve and persist a channel. Updates username if changed.

        Does NOT auto-enable or auto-trust the channel.
        """
        resolved = await self.resolve_channel(username)
        if resolved is None:
            return None

        tg_id = resolved["telegram_channel_id"]

        # Check if channel already exists by stable ID
        existing = (
            session.query(TelegramChannel)
            .filter_by(telegram_channel_id=tg_id)
            .first()
        )

        if existing:
            # Update mutable fields (username can change)
            existing.public_username = resolved["public_username"]
            existing.public_url = resolved["public_url"]
            existing.display_name = resolved["display_name"]
            existing.access_hash = resolved["access_hash"]
            if existing.source_state == "candidate":
                existing.source_state = "configured"
            return existing

        # Create new source + telegram_channel
        clean = username.lstrip("@")
        source = Source(
            name=f"telegram_{tg_id}",
            type="telegram",
            url=f"https://t.me/{resolved['public_username']}" if resolved["public_username"] else f"@{clean}",
            language=language,
            category=category,
            trust_class=trust_class,
            enabled=False,  # never auto-enable
            config={"channel_username": clean, "telegram_channel_id": tg_id},
            health_status="configured",
        )
        session.add(source)
        session.flush()

        channel = TelegramChannel(
            source_id=source.id,
            telegram_channel_id=tg_id,
            access_hash=resolved["access_hash"],
            public_username=resolved["public_username"],
            public_url=resolved["public_url"],
            display_name=resolved["display_name"],
            language=language,
            category=category,
            trust_class=trust_class,
            source_state="configured",
            enabled=False,
        )
        session.add(channel)
        session.flush()
        return channel

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        """Collect new messages from a Telegram channel since last cursor.

        Incremental: only fetches messages newer than last_message_id.
        Overlap safety window: fetches a few messages before cursor to catch
        late edits and ensure idempotency.
        """
        if not self.configured:
            raise CollectionError("MTProto not configured", source.url, recoverable=False)

        await self._ensure_client()

        # Get telegram channel metadata
        session: Session = Session.object_session(source)  # type: ignore[assignment]
        tg_channel = (
            session.query(TelegramChannel)
            .filter_by(source_id=source.id)
            .first()
        )
        if not tg_channel:
            raise CollectionError(
                f"No telegram_channels row for source {source.id}",
                source.url,
                recoverable=False,
            )

        detached_for_io = type(session).__module__.startswith("sqlalchemy.")
        if detached_for_io:
            session.expunge(source)
            session.expunge(tg_channel)
            session.commit()

        # Check FloodWait
        if tg_channel.floodwait_until and tg_channel.floodwait_until > datetime.now(UTC):
            wait = (tg_channel.floodwait_until - datetime.now(UTC)).total_seconds()
            raise CollectionError(
                f"FloodWait active: {wait:.0f}s remaining",
                source.url,
                recoverable=True,
            )

        channel_username = source.config.get("channel_username", "")
        tg_channel_id = tg_channel.telegram_channel_id
        last_msg_id = tg_channel.last_message_id or 0

        # Overlap window: fetch from a few messages before last to catch edits
        # ponytail: simple offset — re-check last 5 message IDs for edit safety
        overlap_offset = max(0, last_msg_id - 5)

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
            async for msg in self._client.iter_messages(
                channel_username,
                min_id=overlap_offset,
                limit=100,
            ):
                if not isinstance(msg, Message):
                    continue
                text = msg.text or ""
                if not text.strip():
                    # still capture caption-only or media-with-caption
                    caption = ""
                    if msg.media:
                        caption = getattr(msg.media, "caption", "") or ""
                    if not caption.strip():
                        continue
                    text = caption

                record = adapt_telethon_message(
                    msg,
                    source_id=source.id,
                    source_name=source.name,
                    source_url=source.url,
                    telegram_channel_id=tg_channel_id,
                    public_username=tg_channel.public_username,
                )
                items.append(record.to_dict())

            logger.info(f"Collected {len(items)} messages from {channel_username}")
            return items

        except FloodWaitError as e:
            wait_seconds = int(getattr(e, "seconds", 60))
            logger.warning(f"FloodWait for {channel_username}: must wait {wait_seconds}s")
            # Persist FloodWait state
            from datetime import timedelta

            tg_channel.floodwait_until = datetime.now(UTC) + timedelta(seconds=wait_seconds)
            tg_channel.source_state = "rate_limited"
            tg_channel.current_error = f"FloodWait: {wait_seconds}s"
            tg_channel.error_category = "floodwait"
            if detached_for_io:
                tg_channel = session.merge(tg_channel)
            session.flush()
            raise CollectionError(
                f"FloodWait: {wait_seconds}s",
                source.url,
                recoverable=True,
            ) from e

        except Exception as e:
            err_str = str(e)
            logger.error(f"Telegram collection error for {channel_username}: {err_str}")

            # Classify error
            if "ChannelPrivateError" in type(e).__name__ or "private" in err_str.lower():
                tg_channel.source_state = "inaccessible"
                tg_channel.error_category = "channel_private"
            elif "UsernameNotOccupiedError" in type(e).__name__ or "not occupied" in err_str.lower():
                tg_channel.source_state = "invalid"
                tg_channel.error_category = "username_invalid"
            elif "AuthKeyError" in type(e).__name__ or "auth" in err_str.lower():
                tg_channel.source_state = "authentication-required"
                tg_channel.error_category = "auth_error"
            else:
                tg_channel.source_state = "degraded"
                tg_channel.error_category = "collection_error"

            tg_channel.current_error = err_str[:500]
            if detached_for_io:
                tg_channel = session.merge(tg_channel)
            session.flush()

            raise CollectionError(
                f"Telegram collection error: {err_str}",
                source.url,
                recoverable=not ("auth" in err_str.lower() or "private" in err_str.lower()),
            ) from e

    def validate_url(self, source_url: str) -> bool:
        """Telegram public channel: @username or https://t.me/username."""
        return (
            source_url.startswith("@")
            or "t.me/" in source_url
            or "telegram.me/" in source_url
        )

    def persist_items(
        self,
        session: Session,
        source: Source,
        items: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Persist collected items with edit handling and idempotency.

        - New messages: insert as new RawItem
        - Edited messages: update existing RawItem in place
        - Duplicate (same channel+message_id): skip

        Returns stats dict.
        """
        stats = {"new": 0, "updated": 0, "skipped": 0}
        tg_channel = (
            session.query(TelegramChannel)
            .filter_by(source_id=source.id)
            .first()
        )

        for item in items:
            tg_channel_id = item.get("telegram_channel_id", 0)
            msg_id = item.get("message_id", 0)
            if not tg_channel_id or not msg_id:
                stats["skipped"] += 1
                continue

            # Check for existing item by telegram identity
            existing = (
                session.query(RawItem)
                .filter(
                    RawItem.telegram_channel_id == tg_channel_id,
                    RawItem.telegram_message_id == msg_id,
                )
                .first()
            )

            content_hash = item.get("content_hash", "")
            edit_date = item.get("edit_date")

            if existing:
                if existing.content_hash == content_hash and not existing.is_deleted:
                    # Identical — skip
                    stats["skipped"] += 1
                    continue
                # Edit: update in place
                existing.raw_data = item
                existing.content_hash = content_hash
                existing.is_deleted = False
                if edit_date:
                    from datetime import datetime as _dt

                    try:
                        if edit_date.endswith("Z"):
                            edit_date = edit_date[:-1] + "+00:00"
                        existing.edit_ts = _dt.fromisoformat(edit_date)
                    except (ValueError, TypeError):
                        pass
                stats["updated"] += 1
            else:
                # New item
                raw_item = RawItem(
                    source_id=source.id,
                    raw_data=item,
                    content_hash=content_hash,
                    telegram_channel_id=tg_channel_id,
                    telegram_message_id=msg_id,
                    is_deleted=False,
                )
                if edit_date:
                    from datetime import datetime as _dt

                    try:
                        if edit_date.endswith("Z"):
                            edit_date = edit_date[:-1] + "+00:00"
                        raw_item.edit_ts = _dt.fromisoformat(edit_date)
                    except (ValueError, TypeError):
                        pass
                session.add(raw_item)
                stats["new"] += 1

            # Update channel cursor
            if tg_channel:
                if not tg_channel.last_message_id or msg_id > tg_channel.last_message_id:
                    tg_channel.last_message_id = msg_id
                pub_date = item.get("date")
                if pub_date:
                    try:
                        if pub_date.endswith("Z"):
                            pub_date = pub_date[:-1] + "+00:00"
                        dt = datetime.fromisoformat(pub_date)
                        if not tg_channel.last_observed_ts or dt > tg_channel.last_observed_ts:
                            tg_channel.last_observed_ts = dt
                    except (ValueError, TypeError):
                        pass

        if tg_channel:
            tg_channel.last_collected_at = datetime.now(UTC)
            if tg_channel.source_state in ("degraded", "rate_limited"):
                tg_channel.source_state = "healthy"
                tg_channel.current_error = None
                tg_channel.error_category = None
                tg_channel.floodwait_until = None
            elif tg_channel.source_state == "configured":
                tg_channel.source_state = "healthy"

        session.flush()
        return stats

    def mark_deleted(
        self,
        session: Session,
        telegram_channel_id: int,
        message_id: int,
    ) -> bool:
        """Mark a stored item as deleted. Does not destroy historical data.

        Returns True if an item was found and marked.
        """
        existing = (
            session.query(RawItem)
            .filter(
                RawItem.telegram_channel_id == telegram_channel_id,
                RawItem.telegram_message_id == message_id,
            )
            .first()
        )
        if existing and not existing.is_deleted:
            existing.is_deleted = True
            session.flush()
            return True
        return False

    def detect_gaps(
        self,
        session: Session,
        source_id: int,
        collected_message_ids: list[int],
    ) -> list[dict[str, Any]]:
        """Detect message ID gaps for reconciliation scheduling.

        Only detects gaps — does not trigger infinite backfill.
        """
        if len(collected_message_ids) < 2:
            return []

        sorted_ids = sorted(collected_message_ids)
        gaps: list[dict[str, Any]] = []

        for i in range(1, len(sorted_ids)):
            prev = sorted_ids[i - 1]
            curr = sorted_ids[i]
            if curr - prev > 1:
                gap_start = prev + 1
                gap_end = curr - 1
                # Check if gap already recorded
                existing_gap = (
                    session.query(TelegramMessageGap)
                    .filter(
                        TelegramMessageGap.source_id == source_id,
                        TelegramMessageGap.gap_start_id == gap_start,
                        TelegramMessageGap.gap_end_id == gap_end,
                        TelegramMessageGap.status == "open",
                    )
                    .first()
                )
                if not existing_gap:
                    gap = TelegramMessageGap(
                        source_id=source_id,
                        gap_start_id=gap_start,
                        gap_end_id=gap_end,
                        status="open",
                        unresolved_count=gap_end - gap_start + 1,
                    )
                    session.add(gap)
                    gaps.append({
                        "start": gap_start,
                        "end": gap_end,
                        "count": gap_end - gap_start + 1,
                    })

        if gaps:
            session.flush()
        return gaps

    async def health_check(self, source: Source) -> bool:
        """Check if channel is accessible."""
        if not self.configured:
            return False
        try:
            await self._ensure_client()
            channel_username = source.config.get("channel_username", "")
            entity = await self._client.get_entity(channel_username)
            return entity is not None
        except Exception as e:
            logger.warning(f"Channel {source.url} health check failed: {e}")
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.disconnect()
            self._client = None

    async def get_self_identity(self) -> dict[str, Any] | None:
        """Get authenticated account identity for verification.

        Returns dict with numeric self ID and first name only.
        Never returns phone number, api_hash, or session data.
        """
        await self._ensure_client()
        try:
            me = await self._client.get_me()
            return {
                "self_id": int(getattr(me, "id", 0)),
                "first_name": getattr(me, "first_name", ""),
                "username": getattr(me, "username", ""),
                "is_authorized": True,
            }
        except Exception as e:
            logger.error(f"Failed to get self identity: {e}")
            return None
