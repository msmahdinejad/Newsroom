"""Gate 6 bounded production-style collection across all platform types.

Collects a capped number of sources per type (RSS, GitHub, Reddit, web_page,
YouTube) to populate enough material for a scheduled-style report without
hammering external sites. Telegram MTProto is attempted but tolerated when
the network connection is refused (environmental). Failures are per-source.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from newsroom.logging import setup_logging
from newsroom.pipeline.collect import collect_sources
from newsroom.storage.database import get_db

CAPS = [
    ("rss", 30),
    ("github_releases", 30),
    ("reddit_subreddit", 15),
    ("web_page", 20),
    ("youtube_rss", 15),
    ("telegram", 3),
]


async def main() -> int:
    setup_logging()
    total_new = 0
    total_sources = 0
    total_failed: list[str] = []
    for stype, cap in CAPS:
        with get_db() as db:
            res = await collect_sources(db, source_type=stype, limit_per_source=10, max_sources=cap)
        n = res.get("new_items", 0)
        s = res.get("sources", 0)
        f = res.get("failed", [])
        total_new += n
        total_sources += s
        total_failed += f
        print(f"[{stype}] sources={s} new={n} failed={len(f)}")
    print(f"\n[TOTAL] sources={total_sources} new={total_new} failed={len(total_failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
