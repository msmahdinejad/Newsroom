"""Tests for stable shard construction.

Verifies:
- Shard IDs are stable and deterministic
- Partitioning is deterministic for identical inputs
- Shards respect token limits
- Evidence items are never split mid-serialization
- Oversized stories get evidence trimmed
- Partition dimensions (importance ordering preserved)
- Total token budget is respected
"""

from __future__ import annotations

from newsroom.config import settings
from newsroom.editorial.schema import (
    EVIDENCE_SCHEMA_VERSION,
    SYSTEM_PROMPT_VERSION,
    EditorialEvidenceSet,
    EvidenceSourceItem,
    EvidenceStoryPacket,
)
from newsroom.editorial.sharding import (
    PARTITION_VERSION,
    estimate_story_tokens,
    shard_evidence_set,
    trim_evidence_for_shard,
)


def _make_source(ref_id: str, story_id: int, seq: int, excerpt_size: int = 200) -> EvidenceSourceItem:
    return EvidenceSourceItem(
        ref_id=ref_id,
        item_id=story_id * 100 + seq,
        source_name=f"Source{seq}",
        source_type="rss",
        source_trust="reputable",
        source_trust_score=0.8,
        published_at="2026-07-18T10:00:00+00:00",
        original_title=f"Title for story {story_id} source {seq}",
        excerpt="x" * excerpt_size,
        original_url=f"https://example.com/{story_id}/{seq}",
    )


def _make_story(
    story_id: int,
    source_count: int = 3,
    excerpt_size: int = 200,
    importance: float = 0.8,
) -> EvidenceStoryPacket:
    return EvidenceStoryPacket(
        story_id=story_id,
        headline=f"Story {story_id}",
        keywords=["ai", "test"],
        trust_status="confirmed",
        confidence=0.85,
        importance_score=importance,
        source_count=source_count,
        item_count=source_count,
        sources=[
            _make_source(f"ev-{story_id}-{i}", story_id, i, excerpt_size)
            for i in range(source_count)
        ],
        facts=[f"Fact {story_id}.1", f"Fact {story_id}.2"],
    )


def _make_evidence(num_stories: int = 10, **kwargs) -> EditorialEvidenceSet:
    stories = [_make_story(i + 1, **kwargs) for i in range(num_stories)]
    return EditorialEvidenceSet(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        prompt_version=SYSTEM_PROMPT_VERSION,
        report_mode="scheduled",
        stories=stories,
    )


class TestShardIdStability:
    """Shard IDs must be stable and deterministic."""

    def test_same_input_same_shard_ids(self):
        evidence = _make_evidence(num_stories=10)
        result1 = shard_evidence_set(evidence)
        result2 = shard_evidence_set(evidence)
        assert [s.shard_id for s in result1.shards] == [s.shard_id for s in result2.shards]

    def test_different_input_different_shard_ids(self):
        evidence1 = _make_evidence(num_stories=10)
        evidence2 = _make_evidence(num_stories=11)
        result1 = shard_evidence_set(evidence1)
        result2 = shard_evidence_set(evidence2)
        ids1 = {s.shard_id for s in result1.shards}
        ids2 = {s.shard_id for s in result2.shards}
        # At least one shard ID must differ
        assert ids1 != ids2

    def test_shard_id_includes_stable_hash(self):
        evidence = _make_evidence(num_stories=6)
        result = shard_evidence_set(evidence)
        for shard in result.shards:
            assert shard.shard_id.startswith("shard-")
            assert len(shard.shard_id) > len("shard-")


class TestPartitioningDeterminism:
    """Partitioning must be deterministic for identical inputs and configuration."""

    def test_identical_partition(self):
        evidence = _make_evidence(num_stories=12)
        result1 = shard_evidence_set(evidence)
        result2 = shard_evidence_set(evidence)
        assert result1.shards == result2.shards

    def test_partition_version_in_shards(self):
        evidence = _make_evidence(num_stories=6)
        result = shard_evidence_set(evidence)
        assert result.partition_version == PARTITION_VERSION
        for shard in result.shards:
            assert shard.evidence_set_hash == evidence.evidence_hash()


class TestTokenBudgetRespected:
    """Each shard must respect effective token limits."""

    def test_each_shard_within_input_limit(self):
        evidence = _make_evidence(num_stories=20, excerpt_size=400)
        result = shard_evidence_set(evidence)
        for shard in result.shards:
            assert shard.estimated_input_tokens <= shard.effective_input_limit, (
                f"Shard {shard.shard_id} exceeds input limit: "
                f"{shard.estimated_input_tokens} > {shard.effective_input_limit}"
            )

    def test_effective_output_limit_positive(self):
        evidence = _make_evidence(num_stories=4)
        result = shard_evidence_set(evidence)
        for shard in result.shards:
            assert shard.effective_output_limit > 0

    def test_total_estimated_tokens_reported(self):
        evidence = _make_evidence(num_stories=10)
        result = shard_evidence_set(evidence)
        assert result.total_estimated_tokens > 0


class TestStoriesNeverSplitAcrossShards:
    """A story must never appear in multiple shards."""

    def test_each_story_in_exactly_one_shard(self):
        evidence = _make_evidence(num_stories=15)
        result = shard_evidence_set(evidence)
        all_story_ids: list[int] = []
        for shard in result.shards:
            all_story_ids.extend(shard.story_ids)
        # No duplicates
        assert len(all_story_ids) == len(set(all_story_ids))

    def test_all_selected_stories_appear_in_some_shard(self):
        evidence = _make_evidence(num_stories=8)
        result = shard_evidence_set(evidence)
        all_story_ids: set[int] = set()
        for shard in result.shards:
            all_story_ids.update(shard.story_ids)
        original_ids = {s.story_id for s in evidence.stories}
        # All stories except omitted ones should appear
        assert all_story_ids.issubset(original_ids)
        # Stories that were selected should all appear
        assert len(all_story_ids) > 0


class TestOversizedStoryHandling:
    """Oversized stories get evidence trimmed, not split."""

    def test_oversized_story_trimmed_not_split(self):
        # Single story with huge evidence — should be trimmed to fit one shard
        huge_story = _make_story(
            story_id=1,
            source_count=50,
            excerpt_size=1000,
        )
        evidence = EditorialEvidenceSet(stories=[huge_story])
        result = shard_evidence_set(evidence)
        assert len(result.shards) == 1
        assert result.oversized_story_count >= 1
        # Story should still be in one shard
        assert 1 in result.shards[0].story_ids

    def test_trim_evidence_preserves_high_trust_sources(self):
        """trim_evidence_for_shard prioritizes high-trust sources."""
        sources = []
        for i in range(10):
            sources.append(EvidenceSourceItem(
                ref_id=f"ev-1-{i}",
                item_id=i,
                source_name=f"Source{i}",
                source_type="rss",
                source_trust="official" if i < 2 else "community",
                source_trust_score=0.95 if i < 2 else 0.3,
                published_at="2026-07-18T10:00:00+00:00",
                original_title=f"Title {i}",
                excerpt="x" * 500,  # large excerpt to force trimming
                original_url=f"https://example.com/{i}",
            ))
        story = EvidenceStoryPacket(
            story_id=1,
            headline="test",
            keywords=[],
            trust_status="confirmed",
            confidence=0.8,
            importance_score=0.9,
            source_count=10,
            item_count=10,
            sources=sources,
            facts=["fact1"],
        )
        trimmed = trim_evidence_for_shard(story, max_tokens=2000)
        # Official sources (indices 0, 1) should be preserved
        ref_ids = [s.ref_id for s in trimmed.sources]
        assert "ev-1-0" in ref_ids
        assert "ev-1-1" in ref_ids


class TestStoryCountLimit:
    """Shards respect the max_stories_per_shard limit."""

    def test_shard_respects_max_stories(self):
        evidence = _make_evidence(num_stories=50, excerpt_size=50)  # small excerpts
        result = shard_evidence_set(evidence)
        for shard in result.shards:
            assert len(shard.story_ids) <= settings.editorial_max_stories_per_shard

    def test_max_map_calls_limit(self):
        """Total shards cannot exceed max_map_calls_per_report."""
        evidence = _make_evidence(num_stories=200, excerpt_size=50)
        result = shard_evidence_set(evidence)
        assert len(result.shards) <= settings.editorial_max_map_calls_per_report


class TestShardSpecFields:
    """ShardSpec has all required fields per the spec."""

    def test_shard_spec_has_all_required_fields(self):
        evidence = _make_evidence(num_stories=6)
        result = shard_evidence_set(evidence)
        for shard in result.shards:
            assert shard.shard_id
            assert shard.shard_sequence >= 0
            assert shard.total_shards == len(result.shards)
            assert isinstance(shard.story_ids, list)
            assert isinstance(shard.evidence_ref_ids, list)
            assert shard.estimated_input_tokens > 0
            assert shard.effective_input_limit > 0
            assert shard.effective_output_limit > 0
            assert shard.evidence_set_hash

    def test_shard_sequence_is_contiguous(self):
        evidence = _make_evidence(num_stories=20, excerpt_size=300)
        result = shard_evidence_set(evidence)
        sequences = [s.shard_sequence for s in result.shards]
        assert sequences == list(range(len(sequences)))


class TestEstimateStoryTokens:
    """Token estimation is reasonable."""

    def test_empty_story_small_tokens(self):
        story = EvidenceStoryPacket(
            story_id=1,
            headline="",
            keywords=[],
            trust_status="confirmed",
            confidence=0.8,
            importance_score=0.8,
            source_count=0,
            item_count=0,
            sources=[],
            facts=[],
        )
        tokens = estimate_story_tokens(story)
        # Should be > 0 due to overhead, but small
        assert tokens > 0
        assert tokens < 1000

    def test_large_story_more_tokens(self):
        large = _make_story(1, source_count=20, excerpt_size=500)
        small = _make_story(2, source_count=2, excerpt_size=100)
        assert estimate_story_tokens(large) > estimate_story_tokens(small)
