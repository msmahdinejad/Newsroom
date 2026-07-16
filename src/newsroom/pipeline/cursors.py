"""Per-source collection cursors — structured JSON metadata, transactional advance.

Cursor advances only after fetched items are successfully persisted.
Failed fetch/persist leaves cursor unchanged. Overlap windows are OK;
content_hash dedup keeps overlap idempotent.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from newsroom.storage.models import CollectionCursor

CURSOR_KEY = "default"


def load_cursor(session: Session, source_id: int, key: str = CURSOR_KEY) -> dict[str, Any]:
    row = (
        session.query(CollectionCursor)
        .filter_by(source_id=source_id, cursor_key=key)
        .first()
    )
    if not row:
        return {}
    try:
        data = json.loads(row.cursor_value)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        # legacy opaque string — treat as last_seen_id
        return {"legacy": row.cursor_value}


def save_cursor(
    session: Session,
    source_id: int,
    meta: dict[str, Any],
    key: str = CURSOR_KEY,
) -> None:
    """Upsert structured cursor. Caller owns transaction/commit."""
    payload = json.dumps(meta, ensure_ascii=False, sort_keys=True, default=str)
    row = (
        session.query(CollectionCursor)
        .filter_by(source_id=source_id, cursor_key=key)
        .first()
    )
    if row:
        row.cursor_value = payload
        row.updated_at = datetime.now(UTC)
    else:
        session.add(
            CollectionCursor(
                source_id=source_id,
                cursor_key=key,
                cursor_value=payload,
            )
        )


def filter_new_items(
    items: list[dict[str, Any]],
    cursor: dict[str, Any],
    *,
    source_type: str,
) -> list[dict[str, Any]]:
    """Drop items already covered by cursor. Keeps overlap band for safety."""
    if not cursor:
        return items

    if source_type == "rss":
        last_pub = cursor.get("last_published")
        seen_ids = set(cursor.get("seen_entry_ids") or [])
        if not last_pub and not seen_ids:
            return items
        out: list[dict[str, Any]] = []
        for it in items:
            eid = str(it.get("entry_id") or "")
            pub = it.get("published") or ""
            if eid and eid in seen_ids:
                continue
            # allow equal published (overlap); only drop strictly older
            if last_pub and pub and pub < last_pub:
                continue
            out.append(it)
        return out

    if source_type == "github_releases":
        last_id = cursor.get("last_release_id")
        if last_id is None:
            return items
        out = []
        for it in items:
            rid = it.get("release_id")
            # keep equal id for overlap/idempotency checks downstream
            if rid is not None and int(rid) < int(last_id):
                continue
            out.append(it)
        return out

    return items


def advance_cursor_from_items(
    cursor: dict[str, Any],
    persisted_items: list[dict[str, Any]],
    *,
    source_type: str,
) -> dict[str, Any]:
    """Compute next cursor from successfully persisted raw payloads only."""
    if not persisted_items:
        return dict(cursor)

    next_c = dict(cursor)
    next_c["updated_at"] = datetime.now(UTC).isoformat()

    if source_type == "rss":
        pubs = [it.get("published") for it in persisted_items if it.get("published")]
        if pubs:
            newest = max(str(p) for p in pubs)
            prev = str(cursor.get("last_published") or "")
            if newest >= prev:
                next_c["last_published"] = newest
        seen = list(cursor.get("seen_entry_ids") or [])
        for it in persisted_items:
            eid = str(it.get("entry_id") or "")
            if eid and eid not in seen:
                seen.append(eid)
        # keep last 200 entry ids for overlap safety
        next_c["seen_entry_ids"] = seen[-200:]
        return next_c

    if source_type == "github_releases":
        ids = [int(it["release_id"]) for it in persisted_items if it.get("release_id") is not None]
        if ids:
            max_id = max(ids)
            prev_id = int(cursor.get("last_release_id") or 0)
            next_c["last_release_id"] = str(max(max_id, prev_id))
        return next_c

    return next_c
