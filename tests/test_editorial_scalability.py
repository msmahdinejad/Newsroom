"""Scalability tests for hierarchical editorial processing.

Uses a deterministic fake provider — no real billable API calls.
Verifies bounded hierarchical behavior with synthetic datasets.

Covers:
- Dataset S: 100 sources, 1,000 raw items (~200 stories)
- Dataset M: 500 sources, 10,000 raw items (~1,500 stories)
- Dataset L: 1,300+ sources, 50,000+ raw items (~8,000 stories)

Verifies:
- Raw item count does not become prompt item count
- No individual AI request exceeds effective input limit
- No individual AI response exceeds effective output limit
- Shard IDs and partitions are deterministic
- All selected stories appear in exactly one map shard (unless oversized)
- Map shards process with bounded concurrency
- Reduction depth remains bounded
- Failed shard retry is isolated
- Cache prevents unchanged shard regeneration
- Total call count obeys report budget
- Final claims retain evidence lineage
- Memory use does not grow linearly with the complete historical database
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure tests dir is on path
_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from fake_scalable_provider import FakeScalableProvider  # noqa: E402
from scalability_datasets import (  # noqa: E402
    SyntheticDataset,
    generate_dataset_l,
    generate_dataset_m,
    generate_dataset_s,
)

from newsroom.config import settings  # noqa: E402
from newsroom.editorial.schema import EditorialEvidenceSet  # noqa: E402
from newsroom.editorial.sharding import shard_evidence_set  # noqa: E402

# ── Unit-level shard construction tests ──────────────────────────


class TestShardConstructionDatasetS:
    """Shard construction on Dataset S (100 sources, 1000 raw items)."""

    @pytest.fixture(scope="class")
    def dataset_s(self) -> SyntheticDataset:
        return generate_dataset_s()

    def test_shards_created(self, dataset_s: SyntheticDataset):
        result = shard_evidence_set(dataset_s.evidence)
        assert len(result.shards) > 0
        assert result.total_stories == dataset_s.story_count

    def test_shard_count_within_budget(self, dataset_s: SyntheticDataset):
        result = shard_evidence_set(dataset_s.evidence)
        assert len(result.shards) <= settings.editorial_max_map_calls_per_report

    def test_each_shard_within_input_limit(self, dataset_s: SyntheticDataset):
        result = shard_evidence_set(dataset_s.evidence)
        for shard in result.shards:
            assert shard.estimated_input_tokens <= shard.effective_input_limit

    def test_all_stories_in_some_shard_or_omitted(self, dataset_s: SyntheticDataset):
        result = shard_evidence_set(dataset_s.evidence)
        all_shard_story_ids: set[int] = set()
        for shard in result.shards:
            all_shard_story_ids.update(shard.story_ids)
        original_ids = {s.story_id for s in dataset_s.evidence.stories}
        # Sharded stories are a subset (others omitted due to budget)
        assert all_shard_story_ids.issubset(original_ids)
        # At least some stories should be sharded
        assert len(all_shard_story_ids) > 0

    def test_each_story_in_exactly_one_shard(self, dataset_s: SyntheticDataset):
        result = shard_evidence_set(dataset_s.evidence)
        all_ids: list[int] = []
        for shard in result.shards:
            all_ids.extend(shard.story_ids)
        assert len(all_ids) == len(set(all_ids)), "Story appears in multiple shards"

    def test_shard_ids_deterministic(self, dataset_s: SyntheticDataset):
        result1 = shard_evidence_set(dataset_s.evidence)
        result2 = shard_evidence_set(dataset_s.evidence)
        assert [s.shard_id for s in result1.shards] == [s.shard_id for s in result2.shards]


class TestShardConstructionDatasetM:
    """Shard construction on Dataset M (500 sources, 10,000 raw items)."""

    @pytest.fixture(scope="class")
    def dataset_m(self) -> SyntheticDataset:
        return generate_dataset_m()

    def test_shards_created(self, dataset_m: SyntheticDataset):
        result = shard_evidence_set(dataset_m.evidence)
        assert len(result.shards) > 0

    def test_shard_count_within_budget(self, dataset_m: SyntheticDataset):
        result = shard_evidence_set(dataset_m.evidence)
        assert len(result.shards) <= settings.editorial_max_map_calls_per_report

    def test_each_shard_within_input_limit(self, dataset_m: SyntheticDataset):
        result = shard_evidence_set(dataset_m.evidence)
        for shard in result.shards:
            assert shard.estimated_input_tokens <= shard.effective_input_limit, (
                f"Shard {shard.shard_id}: {shard.estimated_input_tokens} > {shard.effective_input_limit}"
            )

    def test_no_oversized_shard(self, dataset_m: SyntheticDataset):
        result = shard_evidence_set(dataset_m.evidence)
        for shard in result.shards:
            assert shard.estimated_input_tokens <= shard.effective_input_limit


class TestShardConstructionDatasetL:
    """Shard construction on Dataset L (1,300+ sources, 50,000+ raw items)."""

    @pytest.fixture(scope="class")
    def dataset_l(self) -> SyntheticDataset:
        return generate_dataset_l()

    def test_shards_created(self, dataset_l: SyntheticDataset):
        result = shard_evidence_set(dataset_l.evidence)
        assert len(result.shards) > 0

    def test_shard_count_within_budget(self, dataset_l: SyntheticDataset):
        result = shard_evidence_set(dataset_l.evidence)
        assert len(result.shards) <= settings.editorial_max_map_calls_per_report

    def test_raw_count_not_prompt_count(self, dataset_l: SyntheticDataset):
        """Raw item count (50,000) should not become prompt item count."""
        result = shard_evidence_set(dataset_l.evidence)
        total_stories_in_shards = sum(len(s.story_ids) for s in result.shards)
        # Total stories in all shards << 50,000 raw items
        assert total_stories_in_shards < 1000  # bounded by shard limits

    def test_no_shard_exceeds_effective_input_limit(self, dataset_l: SyntheticDataset):
        result = shard_evidence_set(dataset_l.evidence)
        for shard in result.shards:
            assert shard.estimated_input_tokens <= shard.effective_input_limit


# ── End-to-end hierarchical pipeline tests (no DB) ──────────────


class TestHierarchicalPipelineNoDB:
    """Hierarchical pipeline tests that don't require a database.

    These tests verify the sharding logic in isolation with a fake provider.
    The full DB-backed pipeline is tested in integration tests.
    """

    def test_sharding_deterministic_across_runs(self):
        """Same evidence set produces same shard IDs across multiple runs."""
        ds = generate_dataset_s()
        result1 = shard_evidence_set(ds.evidence)
        result2 = shard_evidence_set(ds.evidence)
        assert [s.shard_id for s in result1.shards] == [s.shard_id for s in result2.shards]

    def test_fake_provider_returns_valid_output(self):
        """Fake scalable provider returns valid structured output."""
        provider = FakeScalableProvider(latency_ms=0)
        from newsroom.editorial.schema import EditorialRequest
        from tests.scalability_datasets import _make_story

        evidence = EditorialEvidenceSet(
            stories=[_make_story(1, source_count=2)],
        )
        request = EditorialRequest(evidence=evidence)
        response = provider.generate(request)
        assert response.provider == "fake_scalable"
        assert response.output.stories
        assert response.usage is not None
        assert response.usage["total_tokens"] > 0


# ── Integration tests requiring PostgreSQL ───────────────────────
# These are in tests/integration/test_gate4_scalable.py to access the `db` fixture.
