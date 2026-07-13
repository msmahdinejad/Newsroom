"""CLI commands for digest generation."""

import argparse

from newsroom.digest.preview import PreviewGenerator
from newsroom.logging import get_logger, setup_logging
from newsroom.storage.database import get_db
from newsroom.storage.models import Story

logger = get_logger(__name__)


def preview_command(args: argparse.Namespace) -> int:
    """Generate Persian digest preview.

    Args:
        args: Parsed arguments

    Returns:
        Exit code
    """
    setup_logging()
    logger.info("Generating digest preview")

    try:
        generator = PreviewGenerator()

        with get_db() as db:
            # Get recent stories
            stories = db.query(Story).order_by(
                Story.created_at.desc()
            ).limit(args.limit).all()

            if not stories:
                print("No stories available for digest")
                return 0

            story_ids = [s.id for s in stories]

            if args.save:
                # Create and persist digest
                digest_id = generator.create_digest(story_ids)
                print(f"✓ Created digest {digest_id} with {len(stories)} stories")
            else:
                # Just print preview
                preview = generator.generate_preview(story_ids)
                print(preview)

            return 0

    except Exception as e:
        logger.error(f"Digest generation failed: {e}")
        print(f"✗ Digest generation failed: {e}")
        return 1
