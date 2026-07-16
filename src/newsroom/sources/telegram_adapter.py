"""Telegram MTProto adapter — narrow boundary between Telethon and Newsroom domain.

The rest of the application never depends on Telethon-specific objects.
All Telethon interaction is contained here and in the collector.

Security: all Telegram content is untrusted data. Records are inert dicts.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TelegramMessageRecord:
    """Structured record extracted from a Telethon message.

    This is the ONLY type that crosses the adapter boundary.
    Contains no Telethon objects — pure data.
    """
    type: str = "telegram"
    source_id: int = 0
    source_name: str = ""
    source_url: str = ""

    # Stable identity
    telegram_channel_id: int = 0
    message_id: int = 0

    # Content
    text: str = ""
    caption: str = ""

    # Timestamps
    date: str | None = None  # ISO format publication timestamp
    edit_date: str | None = None

    # Links
    link: str = ""  # public permalink
    outbound_links: list[str] = field(default_factory=list)

    # Forward attribution
    forward_from_channel_id: int | None = None
    forward_from_channel_name: str | None = None
    forward_from_message_id: int | None = None
    forward_from_date: str | None = None
    forward_timestamp: str | None = None

    # Reply
    reply_to_message_id: int | None = None

    # Media metadata (type only, no downloads)
    media_type: str | None = None  # photo/video/document/sticker/none

    # State
    is_edited: bool = False
    is_deleted: bool = False

    # Content hash for dedup
    content_hash: str = ""

    # Raw structured metadata (sanitized — no auth keys, no session data)
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSONB storage. Content hash computed from text."""
        d = asdict(self)
        if not d["content_hash"]:
            d["content_hash"] = compute_content_hash(d["text"], d["telegram_channel_id"], d["message_id"])
        return d


def compute_content_hash(text: str, channel_id: int, message_id: int) -> str:
    """Deterministic hash for dedup — channel_id:message_id + text."""
    content = f"{channel_id}:{message_id}:{text[:2000]}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def extract_outbound_links(text: str) -> list[str]:
    """Extract URLs from message text."""
    if not text:
        return []
    url_pattern = re.compile(r'https?://[^\s<>"\']+')
    return list(dict.fromkeys(url_pattern.findall(text)))  # dedup preserving order


def build_permalink(username: str | None, message_id: int) -> str:
    """Generate public permalink for a public channel.

    For inaccessible or non-public messages, returns empty string.
    """
    if not username or not message_id:
        return ""
    # Strip @ prefix, strip t.me/ prefix if accidentally passed
    clean = username.lstrip("@")
    if "t.me/" in clean:
        clean = clean.split("t.me/")[-1]
    return f"https://t.me/{clean}/{message_id}"


def adapt_telethon_message(
    msg: Any,
    *,
    source_id: int,
    source_name: str,
    source_url: str,
    telegram_channel_id: int,
    public_username: str | None = None,
) -> TelegramMessageRecord:
    """Convert a Telethon Message object to a TelegramMessageRecord.

    This is the ONLY function that touches Telethon internals.
    All attribute access uses getattr for safety — never crashes on missing fields.
    """
    text = getattr(msg, "text", "") or ""
    caption = ""
    media = getattr(msg, "media", None)
    media_type = _classify_media(media)

    # If no text but has caption on media, use caption
    if not text and media:
        caption = _extract_caption(media)
        text = caption

    message_id = getattr(msg, "id", 0)
    date = _safe_iso(getattr(msg, "date", None))
    edit_date = _safe_iso(getattr(msg, "edit_date", None))
    is_edited = bool(edit_date)

    # Forward metadata
    fwd = _extract_forward_metadata(getattr(msg, "fwd_from", None))

    # Reply metadata
    reply_to = getattr(msg, "reply_to_msg_id", None) or getattr(msg, "reply_to", None)
    reply_to_id = None
    if reply_to and hasattr(reply_to, "reply_to_msg_id"):
        reply_to_id = reply_to.reply_to_msg_id
    elif isinstance(reply_to, int):
        reply_to_id = reply_to

    # Outbound links from text entities + raw text
    outbound = extract_outbound_links(text)

    # Also extract from message entities (URL entities)
    entities = getattr(msg, "entities", []) or []
    for ent in entities:
        url = getattr(ent, "url", None)
        if url:
            outbound.append(url)
    # dedup
    outbound = list(dict.fromkeys(outbound))

    permalink = build_permalink(public_username, message_id)

    return TelegramMessageRecord(
        type="telegram",
        source_id=source_id,
        source_name=source_name,
        source_url=source_url,
        telegram_channel_id=telegram_channel_id,
        message_id=message_id,
        text=text[:5000],
        caption=caption[:2000],
        date=date,
        edit_date=edit_date,
        link=permalink,
        outbound_links=outbound,
        forward_from_channel_id=fwd.get("from_channel_id"),
        forward_from_channel_name=fwd.get("from_channel_name"),
        forward_from_message_id=fwd.get("from_message_id"),
        forward_from_date=fwd.get("from_date"),
        forward_timestamp=fwd.get("forward_timestamp"),
        reply_to_message_id=reply_to_id,
        media_type=media_type,
        is_edited=is_edited,
        is_deleted=False,
        content_hash=compute_content_hash(text, telegram_channel_id, message_id),
        raw_metadata={
            "has_media": media is not None,
            "media_type": media_type,
            "entity_count": len(entities),
            "has_forward": fwd is not None,
            "has_reply": reply_to_id is not None,
        },
    )


def _safe_iso(dt: Any) -> str | None:
    """Safely convert a datetime to ISO format."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def _classify_media(media: Any) -> str | None:
    """Classify media type without downloading anything."""
    if media is None:
        return None
    media_class = type(media).__name__
    if "Photo" in media_class:
        return "photo"
    if "Video" in media_class:
        return "video"
    if "Document" in media_class:
        return "document"
    if "Sticker" in media_class:
        return "sticker"
    if "WebPage" in media_class:
        return "webpage"
    return "other"


def _extract_caption(media: Any) -> str:
    """Extract caption from media if available."""
    # Telethon stores caption in message.text when present,
    # but some media types store it in media.caption
    caption = getattr(media, "caption", None)
    if caption and isinstance(caption, str):
        return caption
    return ""


def _extract_forward_metadata(fwd_from: Any) -> dict[str, Any]:
    """Extract forward attribution from Telethon fwd_from object.

    Does not infer hidden origin information.
    Does not expose private account details.
    """
    if fwd_from is None:
        return {}

    result: dict[str, Any] = {}

    # Telethon ForwardedMessageInfo or MessageFwdHeader
    from_id = getattr(fwd_from, "from_id", None)
    from_name = getattr(fwd_from, "from_name", None)
    channel_post = getattr(fwd_from, "channel_post", None)
    date = getattr(fwd_from, "date", None)

    # Extract channel ID from from_id if it's a PeerChannel
    if from_id is not None:
        channel_id = _extract_peer_id(from_id)
        if channel_id:
            result["from_channel_id"] = channel_id
            channel_name = _extract_peer_name(from_id)
            if channel_name:
                result["from_channel_name"] = channel_name

    if from_name:
        result["from_channel_name"] = from_name

    if channel_post is not None:
        result["from_message_id"] = int(channel_post)

    if date is not None:
        result["from_date"] = _safe_iso(date)
        result["forward_timestamp"] = _safe_iso(date)

    return result


def _extract_peer_id(peer: Any) -> int | None:
    """Extract numeric ID from a Telethon Peer object."""
    if peer is None:
        return None
    # PeerChannel has channel_id, PeerUser has user_id, PeerChat has chat_id
    for attr in ("channel_id", "user_id", "chat_id"):
        val = getattr(peer, attr, None)
        if val is not None:
            return int(val)
    return None


def _extract_peer_name(peer: Any) -> str | None:
    """Extract a public name from a Peer if available (not private user info)."""
    if peer is None:
        return None
    # Only expose channel usernames, never private user names
    username = getattr(peer, "username", None)
    if username:
        return username
    return None
