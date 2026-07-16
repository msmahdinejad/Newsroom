"""Pipeline CLI — same entrypoint as scheduler/bot/cron. Sync (no nested asyncio)."""

import argparse

from newsroom.logging import get_logger, setup_logging
from newsroom.pipeline.runner import EXIT_BUSY, run_pipeline

logger = get_logger(__name__)


def pipeline_run_command(args: argparse.Namespace) -> int:
    """Run complete pipeline via authoritative runner (owns its own asyncio.run)."""
    setup_logging()
    logger.info("Starting complete pipeline")
    result = run_pipeline()
    code = int(result.get("exit_code", 1))
    if code == EXIT_BUSY:
        print("BUSY: pipeline lock held")
    return code
