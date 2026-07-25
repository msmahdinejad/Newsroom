"""One-way Telegram identity fingerprints for durable audit state."""

from __future__ import annotations

import hashlib


def identity_fingerprint(kind: str, value: int | str | None) -> str | None:
    """Return a stable SHA-256 fingerprint without retaining the raw identity."""
    if value is None or str(value).strip() == "":
        return None
    material = f"newsroom:telegram:{kind}:{value}".encode()
    return hashlib.sha256(material).hexdigest()


def command_request_key(
    mode: str,
    user_id: int | str | None,
    chat_id: int | str | None,
    update_id: int | str,
) -> str:
    """Build an idempotency key that contains no Telegram identifiers."""
    user = identity_fingerprint("user", user_id) or "anonymous"
    chat = identity_fingerprint("chat", chat_id) or "unknown"
    material = f"newsroom:command:{mode}:{user}:{chat}:{update_id}".encode()
    return f"{mode}:{hashlib.sha256(material).hexdigest()}"
