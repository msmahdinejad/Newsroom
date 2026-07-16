"""CLI report preview — V2 PersianEditorial (no V1 Digest/eval)."""

import argparse

from newsroom.editorial.persian import PersianEditorial
from newsroom.logging import get_logger, setup_logging
from newsroom.storage.database import get_db
from newsroom.storage.models import Report, Story

logger = get_logger(__name__)


def preview_command(args: argparse.Namespace) -> int:
    """Generate Persian report preview (deterministic)."""
    setup_logging()
    logger.info("Generating report preview")
    try:
        with get_db() as db:
            stories = (
                db.query(Story).order_by(Story.created_at.desc()).limit(args.limit).all()
            )
            if not stories:
                print("No stories available for report")
                return 0
            story_ids = [s.id for s in stories]
            if args.save:
                editorial = PersianEditorial()
                report_id = editorial.generate_report(db, story_ids, report_mode="manual")
                print(f"OK: Created report {report_id} with {len(stories)} stories")
            else:
                # dry preview: generate without relying on V1 path
                editorial = PersianEditorial()
                report_id = editorial.generate_report(db, story_ids, report_mode="preview")
                report = db.query(Report).filter_by(id=report_id).first()
                if report:
                    print(report.content_fa)
            return 0
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        print(f"FAIL: {e}")
        return 1
