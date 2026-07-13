"""Unified pipeline command - runs complete collection→digest flow."""

import argparse

from newsroom.cli.commands.collect import collect_command
from newsroom.cli.commands.digest import preview_command
from newsroom.cli.commands.process import cluster_command, dedupe_command, normalize_command
from newsroom.logging import get_logger, setup_logging

logger = get_logger(__name__)


async def pipeline_run_command(args: argparse.Namespace) -> int:
    """Run complete pipeline: collect → normalize → dedupe → cluster → digest.

    Args:
        args: Parsed arguments

    Returns:
        Exit code
    """
    setup_logging()
    logger.info("Starting complete pipeline")

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🚀 Running Complete Pipeline")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Phase 1: Collection
    print("\n📥 Phase 1: Collection")
    collect_args = argparse.Namespace(source_type=None)
    result = await collect_command(collect_args)
    if result != 0:
        print("✗ Pipeline failed at collection phase")
        return result

    # Phase 2: Normalization
    print("\n⚙️  Phase 2: Normalization")
    normalize_args = argparse.Namespace(limit=1000)
    result = normalize_command(normalize_args)
    if result != 0:
        print("✗ Pipeline failed at normalization phase")
        return result

    # Phase 3: Deduplication
    print("\n🔍 Phase 3: Deduplication")
    dedupe_args = argparse.Namespace(limit=1000)
    result = dedupe_command(dedupe_args)
    if result != 0:
        print("✗ Pipeline failed at deduplication phase")
        return result

    # Phase 4: Clustering
    print("\n📊 Phase 4: Story Clustering")
    cluster_args = argparse.Namespace(limit=1000)
    result = cluster_command(cluster_args)
    if result != 0:
        print("✗ Pipeline failed at clustering phase")
        return result

    # Phase 5: Digest Generation
    print("\n📰 Phase 5: Digest Generation")
    preview_args = argparse.Namespace(limit=50, save=True)
    result = preview_command(preview_args)
    if result != 0:
        print("✗ Pipeline failed at digest phase")
        return result

    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("✓ Pipeline Complete")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return 0
