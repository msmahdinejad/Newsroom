"""Report generation CLI command through the production editorial path."""

import argparse

from newsroom.logging import get_logger, setup_logging

logger = get_logger(__name__)


def report_command(args: argparse.Namespace) -> int:
    """Generate and deliver one manual report with the configured AI router."""
    setup_logging()
    logger.info("Generating report")
    from newsroom.pipeline.runner import PipelineRequest, run_pipeline

    mode_by_source = {
        "default": "manual",
        "all": "manual_comprehensive",
        "telegram": "platform_telegram",
        "x": "platform_x",
        "web": "platform_web",
        "github": "platform_github",
        "reddit": "platform_reddit",
    }
    result = run_pipeline(
        blocking_lock=True,
        request=PipelineRequest(
            report_mode=mode_by_source[getattr(args, "source", "default")],
            digest_slug=getattr(args, "digest", "default"),
        ),
    )

    if result["status"] == "ok":
        print(f"OK: report {result['report_id']} delivery {result['delivery_id']}")
        return 0
    print(f"FAIL: {result.get('error') or result['status']}")
    return int(result.get("exit_code", 1) or 1)
