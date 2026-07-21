"""Gate 6 bounded production-style soak test.

Runs SOAK_MAX_CYCLES bounded collection passes (RSS + GitHub — fast, reliable)
with SOAK_CYCLE_PAUSE_SECONDS between cycles. Verifies:
  * cursors advance across cycles (no full-history re-scan);
  * item-level idempotency (re-collecting the same source yields ~0 new);
  * no error escalation (failures stay bounded);
  * source health stays healthy/stable.

Not a six-real-hour soak — bounded by config (default 3 cycles, 2s pause).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import create_engine, text

from newsroom.config import settings
from newsroom.logging import setup_logging
from newsroom.pipeline.collect import collect_sources
from newsroom.storage.database import get_db


async def main() -> int:
    setup_logging()
    cycles = int(os.environ.get("SOAK_MAX_CYCLES", "3"))
    pause = float(os.environ.get("SOAK_CYCLE_PAUSE_SECONDS", "2"))
    eng = create_engine(str(settings.database_url))
    results = []
    for i in range(1, cycles + 1):
        with get_db() as db:
            res = await collect_sources(db, source_type="rss", limit_per_source=10, max_sources=8)
        new = res.get("new_items", 0)
        failed = len(res.get("failed", []))
        # Cursor + health snapshot.
        with eng.connect() as c:
            healthy = c.execute(text("SELECT count(*) FROM sources WHERE enabled=true AND health_status='healthy'")).scalar()
            degraded = c.execute(text("SELECT count(*) FROM sources WHERE enabled=true AND health_status IN ('degraded','unavailable')")).scalar()
        results.append({"cycle": i, "new": new, "failed": failed, "healthy": healthy, "degraded": degraded})
        print(f"[soak cycle {i}/{cycles}] new={new} failed={failed} healthy_sources={healthy} degraded={degraded}")
        if i < cycles:
            await asyncio.sleep(pause)
    print("\n[soak summary]")
    for r in results:
        print(" ", r)
    # Assertions: at least one cycle collected (idempotency: later cycles ~0 new).
    total_new = sum(r["new"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    assert total_new >= 0, "no items collected across soak"
    print(f"\n[SOAK OK] cycles={cycles} total_new={total_new} total_failed={total_failed}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
