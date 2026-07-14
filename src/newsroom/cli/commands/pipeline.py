"""Pipeline CLI command — V2."""

import argparse
import asyncio

from newsroom.logging import get_logger, setup_logging

logger = get_logger(__name__)


async def pipeline_run_command(args: argparse.Namespace) -> int:
    """Run complete pipeline: collect → normalize → dedupe → cluster → evidence → report."""
    setup_logging()
    logger.info("Starting complete pipeline")

    print("=" * 40)
    print("Pipeline: collect → report")
    print("=" * 40)

    # Run via the canonical pipeline script
    import os
    import subprocess
    import sys

    project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
    script = os.path.join(project_dir, "scripts", "run_pipeline.py")

    result = subprocess.run(
        [sys.executable, script],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=project_dir,
    )

    # Print stage output
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            print(line)

    if result.returncode != 0 and result.stderr:
        print(f"STDERR: {result.stderr[:500]}")

    return result.returncode
