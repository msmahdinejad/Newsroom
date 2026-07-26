"""Report generation CLI command through the production editorial path."""

import argparse
import os

from newsroom.logging import get_logger, setup_logging

logger = get_logger(__name__)


def report_command(args: argparse.Namespace) -> int:
    """Generate and deliver one manual report with the configured AI router."""
    del args
    setup_logging()
    logger.info("Generating report")
    from newsroom.pipeline.runner import run_pipeline

    previous_mode = os.environ.get("NEWSROOM_REPORT_MODE")
    os.environ["NEWSROOM_REPORT_MODE"] = "manual"
    try:
        result = run_pipeline(blocking_lock=True)
    finally:
        if previous_mode is None:
            os.environ.pop("NEWSROOM_REPORT_MODE", None)
        else:
            os.environ["NEWSROOM_REPORT_MODE"] = previous_mode

    if result["status"] == "ok":
        print(f"OK: report {result['report_id']} delivery {result['delivery_id']}")
        return 0
    print(f"FAIL: {result.get('error') or result['status']}")
    return int(result.get("exit_code", 1) or 1)
