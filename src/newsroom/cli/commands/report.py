"""Report generation CLI command."""

import argparse

from newsroom.logging import get_logger, setup_logging
from newsroom.storage.database import get_db
from newsroom.storage.models import Story

logger = get_logger(__name__)


def report_command(args: argparse.Namespace) -> int:
    """Generate a Persian report from recent stories."""
    setup_logging()
    logger.info("Generating report")

    try:
        from newsroom.editorial.persian import PersianEditorural
        from newsroom.processing.evidence import EvidenceBuilder

        with get_db() as db:
            stories = (
                db.query(Story)
                .order_by(Story.importance_score.desc(), Story.created_at.desc())
                .limit(30)
                .all()
            )

            if not stories:
                print("No stories available")
                return 0

            story_ids = [s.id for s in stories]

            # Build evidence
            ev_builder = EvidenceBuilder()
            ev_builder.build_for_stories(db, story_ids)

            # Generate report
            editorial = PersianEditorial()
            report_id = editorial.generate_report(db, story_ids, report_mode="manual")

            print(f"OK: Created report {report_id} with {len(story_ids)} stories")
            return 0
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        print(f"FAIL: {e}")
        return 1
