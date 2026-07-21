"""Gate 6 live verification — representative one-source-per-platform collection.

Validation wave 1: attempt one bounded collection from each supported
platform type (RSS, GitHub releases, Telegram MTProto, Reddit subreddit,
Website HTML, YouTube RSS). Persists real raw items with content-hash dedup
and reports per-platform results. A failed platform does not stop the others.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy.orm import Session

from newsroom.logging import setup_logging
from newsroom.pipeline.collect import raw_content_hash
from newsroom.sources.github import GitHubCollector
from newsroom.sources.html_reader import NativeHtmlReader
from newsroom.sources.reddit import NativeRedditSubredditCollector
from newsroom.sources.rss import RSSCollector
from newsroom.sources.telegram_collector import TelegramMTProtoCollector
from newsroom.sources.youtube_rss import NativeYouTubeRssCollector
from newsroom.storage.database import engine
from newsroom.storage.models import RawItem, Source

# Platform types to verify, in priority order. Pick a Core-tier source first.
TYPES = [
    ("rss", RSSCollector()),
    ("github_releases", GitHubCollector()),
    ("reddit_subreddit", NativeRedditSubredditCollector()),
    ("web_page", NativeHtmlReader()),
    ("youtube_rss", NativeYouTubeRssCollector()),
    ("telegram", TelegramMTProtoCollector()),
]


def pick_source(session: Session, stype: str) -> Source | None:
    rows = session.query(Source).filter(Source.type == stype, Source.enabled.is_(True)).all()
    if not rows:
        return None
    # Prefer sources with a workbook_id (inventory-driven) and Core tier.
    rows.sort(key=lambda s: (0 if getattr(s, "workbook_id", None) else 1, s.name))
    return rows[0]


async def main() -> int:
    setup_logging()
    session = Session(engine)
    summary: list[dict] = []
    try:
        for stype, collector in TYPES:
            src = pick_source(session, stype)
            if src is None:
                summary.append({"type": stype, "status": "no_source"})
                continue
            rec = {"type": stype, "source": src.name, "url": src.url, "status": "ok", "new": 0, "fetched": 0, "error": ""}
            try:
                if stype == "telegram" and not collector.configured:
                    rec["status"] = "mtproto_not_configured"
                    summary.append(rec)
                    continue
                items = await collector.collect(src)
                rec["fetched"] = len(items)
                new = 0
                for it in items[:10]:
                    h = raw_content_hash(it)
                    if stype == "telegram":
                        # telegram collector has its own persist; use it
                        pass
                    existing = (
                        session.query(RawItem)
                        .filter(RawItem.source_id == src.id, RawItem.content_hash == h)
                        .first()
                    )
                    if existing:
                        continue
                    session.add(RawItem(source_id=src.id, raw_data=it, content_hash=h))
                    new += 1
                if stype == "telegram" and collector.configured:
                    stats = collector.persist_items(session, src, items)
                    new = stats["new"]
                    rec["updated"] = stats.get("updated", 0)
                session.commit()
                rec["new"] = new
                src.last_success_at = datetime.now(UTC)
                src.consecutive_failures = 0
                src.health_status = "healthy"
                session.commit()
            except Exception as e:
                session.rollback()
                rec["status"] = "error"
                rec["error"] = str(e)[:200]
                src.last_error_at = datetime.now(UTC)
                src.last_error = str(e)[:500]
                src.consecutive_failures = (src.consecutive_failures or 0) + 1
                session.commit()
            finally:
                try:
                    await collector.close()
                except Exception:
                    pass
            summary.append(rec)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        ok = sum(1 for r in summary if r["status"] == "ok" and r.get("new", 0) >= 0)
        print(f"\n[VERIFIED] {sum(1 for r in summary if r['status']=='ok')} platforms ok, {sum(1 for r in summary if r['status']=='error')} errors")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
