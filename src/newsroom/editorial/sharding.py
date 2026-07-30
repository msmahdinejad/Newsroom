"""Stable shard construction for bounded editorial AI processing.

Partitions stories into bounded shards based on estimated token size.
Each shard is a self-contained unit that fits within effective token limits.
Partitioning is deterministic for identical inputs and configuration.

Key invariants:
- Stories are never split across shards
- Evidence items are never truncated mid-serialization
- Shard IDs are stable and deterministic
- Oversized stories get evidence trimmed (not split)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from newsroom.config import settings
from newsroom.editorial.limits import effective_output_limit
from newsroom.editorial.schema import EditorialEvidenceSet, EvidenceStoryPacket
from newsroom.logging import get_logger

logger = get_logger(__name__)

# Token estimation: ~4 chars per token for mixed text
CHARS_PER_TOKEN = 4
# System prompt overhead tokens (measured from prompt builder)
PROMPT_OVERHEAD_TOKENS = 800
# Evidence metadata overhead per story
STORY_OVERHEAD_TOKENS = 200

PARTITION_VERSION = "g4sp-v1"


@dataclass
class ShardSpec:
    """Specification for one editorial shard."""

    shard_id: str
    shard_sequence: int
    total_shards: int
    story_ids: list[int]
    evidence_ref_ids: list[str]
    estimated_input_tokens: int
    effective_input_limit: int
    effective_output_limit: int
    evidence_set_hash: str


@dataclass
class ShardingResult:
    """Result of sharding an evidence set."""

    shards: list[ShardSpec]
    partition_version: str
    total_stories: int
    omitted_stories: int
    oversized_story_count: int
    total_estimated_tokens: int


def estimate_story_tokens(story: EvidenceStoryPacket) -> int:
    """Estimate the token count for one story in the evidence set."""
    total_chars = STORY_OVERHEAD_TOKENS * CHARS_PER_TOKEN  # metadata
    total_chars += len(story.headline)
    total_chars += len(" ".join(story.keywords))
    for fact in story.facts:
        total_chars += len(fact)
    for src in story.sources:
        total_chars += len(src.original_title or "")
        total_chars += len(src.excerpt or "")
        total_chars += len(src.original_url or "")
        total_chars += 50  # metadata fields
    return total_chars // CHARS_PER_TOKEN


def trim_evidence_for_shard(
    story: EvidenceStoryPacket,
    max_tokens: int,
) -> EvidenceStoryPacket:
    """Trim evidence for an oversized story to fit within token limit.

    Prioritizes:
    1. Official and high-trust sources
    2. Conflict evidence
    3. Most recent sources
    """
    if estimate_story_tokens(story) <= max_tokens:
        return story

    # Sort sources by trust score descending, then published_at descending
    sorted_sources = sorted(
        story.sources,
        key=lambda s: (s.source_trust_score, s.published_at or ""),
        reverse=True,
    )

    # Keep trimming until we fit
    trimmed = sorted_sources[:]
    while (
        trimmed
        and estimate_story_tokens(EvidenceStoryPacket(**{**story.model_dump(), "sources": trimmed}))
        > max_tokens
    ):
        trimmed.pop()  # Remove lowest-priority source

    logger.debug(f"Trimmed story {story.story_id}: {len(story.sources)} → {len(trimmed)} sources")
    return EvidenceStoryPacket(**{**story.model_dump(), "sources": trimmed})


def compute_effective_shard_limits() -> tuple[int, int]:
    """Calculate effective input and output limits for shards."""
    configured_input = settings.editorial_shard_input_token_limit
    configured_output = settings.editorial_shard_output_token_limit
    effective_output = effective_output_limit(configured_output)
    # Input is bounded by the shard limit and the app safety cap
    effective_input = min(configured_input, settings.editorial_max_input_tokens)
    return effective_input, effective_output


def shard_evidence_set(
    evidence: EditorialEvidenceSet,
) -> ShardingResult:
    """Partition an evidence set into bounded shards.

    Stories are ordered by importance, then greedily packed into shards
    up to the effective input token limit. Each shard gets a stable ID
    based on its contents.
    """
    effective_input, effective_output = compute_effective_shard_limits()
    per_shard_token_budget = effective_input - PROMPT_OVERHEAD_TOKENS

    if per_shard_token_budget <= 0:
        logger.error("Effective input limit too small for sharding")
        return ShardingResult(
            shards=[],
            partition_version=PARTITION_VERSION,
            total_stories=len(evidence.stories),
            omitted_stories=len(evidence.stories),
            oversized_story_count=0,
            total_estimated_tokens=0,
        )

    # Stories already ordered by importance in evidence builder
    stories = evidence.stories
    max_stories_per_shard = settings.editorial_max_stories_per_shard
    max_map_calls = settings.editorial_max_map_calls_per_report

    shards: list[list[EvidenceStoryPacket]] = []
    current_shard: list[EvidenceStoryPacket] = []
    current_tokens = 0
    oversized_count = 0
    total_tokens = 0

    for story in stories:
        story_tokens = estimate_story_tokens(story)

        # Check if this story alone exceeds the per-shard budget
        if story_tokens > per_shard_token_budget:
            trimmed = trim_evidence_for_shard(story, per_shard_token_budget)
            story_tokens = estimate_story_tokens(trimmed)
            oversized_count += 1
            story = trimmed

        # If adding this story would exceed the shard budget or story count limit
        if current_shard and (
            current_tokens + story_tokens > per_shard_token_budget
            or len(current_shard) >= max_stories_per_shard
        ):
            shards.append(current_shard)
            current_shard = []
            current_tokens = 0

        # If we've hit the max map calls limit, stop
        if len(shards) >= max_map_calls:
            break

        current_shard.append(story)
        current_tokens += story_tokens
        total_tokens += story_tokens

    if current_shard and len(shards) < max_map_calls:
        shards.append(current_shard)

    # Build shard specs with stable IDs
    shard_specs: list[ShardSpec] = []
    for i, shard_stories in enumerate(shards):
        story_ids = [s.story_id for s in shard_stories]
        ref_ids: list[str] = []
        for s in shard_stories:
            ref_ids.extend(src.ref_id for src in s.sources)

        # Stable shard ID: hash of sorted story IDs + partition version
        shard_hash = hashlib.sha256(
            f"{PARTITION_VERSION}:{','.join(str(sid) for sid in sorted(story_ids))}".encode()
        ).hexdigest()[:16]
        shard_id = f"shard-{shard_hash}"

        estimated_tokens = (
            sum(estimate_story_tokens(s) for s in shard_stories) + PROMPT_OVERHEAD_TOKENS
        )

        shard_specs.append(
            ShardSpec(
                shard_id=shard_id,
                shard_sequence=i,
                total_shards=len(shards),
                story_ids=story_ids,
                evidence_ref_ids=ref_ids,
                estimated_input_tokens=estimated_tokens,
                effective_input_limit=effective_input,
                effective_output_limit=effective_output,
                evidence_set_hash=evidence.evidence_hash(),
            )
        )

    omitted = len(stories) - sum(len(s.story_ids) for s in shard_specs)

    return ShardingResult(
        shards=shard_specs,
        partition_version=PARTITION_VERSION,
        total_stories=len(stories),
        omitted_stories=omitted,
        oversized_story_count=oversized_count,
        total_estimated_tokens=total_tokens,
    )
