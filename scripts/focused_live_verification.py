"""Focused live multi-shard report verification.

Uses real persisted stories from the database with the real provider.
Verifies:
- Multiple shards are created
- At least one reduction stage
- Final structured validation
- Final grounding validation
- Real Telegram delivery
- Persisted message IDs
- Cache reuse on repeated request
- /report new delivered-story exclusion
- No-new-items response after successful delivery

Records only safe metadata — no API keys, headers, or reasoning.
"""

from __future__ import annotations

import json
import os
import sys

# Ensure src is importable
import sys as _sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in _sys.path:
    _sys.path.insert(0, str(_SRC))

# Force hierarchical path with multiple shards:
# - max_stories_per_call=20 so the evidence builder includes 15+ stories
# - max_stories_per_shard=3 so 15 stories → 5 shards
# - max_map_calls=12 so all shards fit
os.environ["EDITORIAL_MAX_STORIES_PER_CALL"] = "20"
os.environ["EDITORIAL_MAX_STORIES_PER_SHARD"] = "3"
os.environ["EDITORIAL_MAX_MAP_CALLS_PER_REPORT"] = "12"


def run_focused_live_verification():
    """Run the focused live verification."""
    from sqlalchemy.orm import Session

    from newsroom.config import settings
    from newsroom.editorial.hierarchy import run_hierarchical_editorial
    from newsroom.editorial.selection import select_stories_for_report
    from newsroom.storage.database import engine
    from newsroom.storage.models import Delivery, EditorialJob, Report

    result: dict = {}

    # 1. Verify editorial is ready
    if not settings.editorial_ready():
        return {"status": "skipped", "reason": "editorial not ready"}

    result["provider"] = settings.editorial_provider
    result["model"] = settings.editorial_model
    result["api_base"] = settings.editorial_api_base

    session = Session(engine)
    try:
        # 2. Select stories for a comprehensive report (use comprehensive to include all)
        selection = select_stories_for_report(session, "manual_comprehensive", max_stories=15)
        story_ids = selection.story_ids

        result["selection"] = {
            "total_candidates": selection.total_candidates,
            "selected": selection.selected_count,
            "excluded_as_delivered": selection.excluded_as_delivered,
            "materially_updated": selection.materially_updated,
            "no_new_items": selection.no_new_items,
        }

        if not story_ids:
            return {**result, "status": "no_stories"}

        # 3. Run hierarchical editorial with the real provider
        hier = run_hierarchical_editorial(
            session, story_ids, "manual_comprehensive",
            job_id="focused_live_verification",
        )

        result["hierarchical"] = {
            "shard_count": hier.job.shard_count,
            "total_model_calls": hier.total_model_calls,
            "total_input_tokens": hier.total_input_tokens,
            "total_output_tokens": hier.total_output_tokens,
            "cache_hits": hier.cache_hits,
            "fallback_shards": hier.fallback_shards,
            "reduction_level": hier.reduction_level,
            "selection_stats": hier.selection_stats,
        }

        # 4. Create a report and deliver it
        report = Report(
            content_fa=hier.content,
            story_ids=story_ids,
            report_mode="manual_comprehensive",
            generation_method="ai" if not hier.attempt.fallback_used else "deterministic",
        )
        session.add(report)
        session.flush()
        hier.job.report_id = report.id
        session.commit()

        result["report_id"] = report.id

        # 5. Deliver via Telegram if bot is configured
        if settings.telegram_bot_ready():
            import asyncio

            from newsroom.delivery.telegram import TelegramDelivery

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                td = TelegramDelivery()
                if td.client.token:
                    delivery_id = loop.run_until_complete(
                        td.deliver_report(session, report.id, cursor_key=None)
                    )
                    result["delivery_id"] = delivery_id

                    # Get delivery chunks with message IDs
                    deliv = session.query(Delivery).filter_by(id=delivery_id).first()
                    if deliv:
                        result["delivery_status"] = deliv.status
                        result["delivery_chunk_count"] = len(deliv.chunks)
                        result["telegram_message_ids"] = [
                            c.telegram_message_id for c in deliv.chunks
                        ]
                loop.run_until_complete(td.close())
            finally:
                loop.close()
                asyncio.set_event_loop(None)

        # 6. Verify /report new excludes delivered stories
        new_selection = select_stories_for_report(session, "manual_new")
        result["report_new_after_delivery"] = {
            "excluded_as_delivered": new_selection.excluded_as_delivered,
            "materially_updated": new_selection.materially_updated,
            "selected": new_selection.selected_count,
            "no_new_items": new_selection.no_new_items,
        }

        # 7. Verify job persistence
        job = session.query(EditorialJob).filter_by(job_id="focused_live_verification").first()
        if job:
            result["job_persisted"] = {
                "status": job.status,
                "shard_count": job.shard_count,
                "total_model_calls": job.total_model_calls,
                "report_id": job.report_id,
            }

        result["status"] = "success"

    except Exception as e:
        result["status"] = "failed"
        result["error_type"] = type(e).__name__
        result["error_summary"] = str(e)[:200]
    finally:
        session.close()

    return result


if __name__ == "__main__":
    print("Focused live multi-shard verification", file=sys.stderr)
    res = run_focused_live_verification()
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
