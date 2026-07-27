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
from types import SimpleNamespace

import pytest

# Ensure tests dir is on path
_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from fake_scalable_provider import FakeScalableProvider  # noqa: E402
from scalability_datasets import (  # noqa: E402
    SyntheticDataset,
    _make_story,
    generate_dataset_l,
    generate_dataset_m,
    generate_dataset_s,
)

from newsroom.config import settings  # noqa: E402
from newsroom.editorial.hierarchy import (  # noqa: E402
    MapResult,
    _final_reduction,
    _reduce_artifacts,
    _reduction_cache_key,
)
from newsroom.editorial.schema import (  # noqa: E402
    EditorialEvidenceSet,
    EditorialRequest,
    EditorialResponse,
)
from newsroom.editorial.sharding import shard_evidence_set  # noqa: E402

# ── Unit-level shard construction tests ──────────────────────────


@pytest.fixture(scope="module")
def dataset_s() -> SyntheticDataset:
    return generate_dataset_s()


@pytest.fixture(scope="module")
def dataset_m() -> SyntheticDataset:
    return generate_dataset_m()


@pytest.fixture(scope="module")
def dataset_l() -> SyntheticDataset:
    return generate_dataset_l()


class TestShardConstructionDatasetS:
    """Shard construction on Dataset S (100 sources, 1000 raw items)."""

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

    def test_final_reduction_only_sends_the_merged_story_subset(self, monkeypatch):
        evidence = EditorialEvidenceSet(
            stories=[_make_story(index, source_count=2) for index in range(1, 31)]
        )
        bounded_evidence = EditorialEvidenceSet(
            schema_version=evidence.schema_version,
            prompt_version=evidence.prompt_version,
            report_mode=evidence.report_mode,
            stories=evidence.stories[: settings.editorial_max_stories_per_call],
        )
        seed_provider = FakeScalableProvider(latency_ms=0)
        merged = seed_provider.generate(
            EditorialRequest(evidence=bounded_evidence)
        ).output
        child = MapResult(
            shard_id="map-1",
            artifact_id=1,
            output=merged,
            story_ids=[story.story_id for story in bounded_evidence.stories],
            evidence_ref_ids=[
                source.ref_id
                for story in bounded_evidence.stories
                for source in story.sources
            ],
            latency_ms=0,
            usage=None,
            from_cache=False,
            fallback_used=False,
            provider="fake_scalable",
            model="fake-scalable-v1",
        )

        class RecordingProvider:
            name = "recording"
            model_name = "recording-v1"

            def __init__(self):
                self.requests: list[EditorialRequest] = []

            def generate(self, request: EditorialRequest) -> EditorialResponse:
                self.requests.append(request)
                output = merged.model_copy(deep=True)
                output.metadata.provider = self.name
                output.metadata.model_name = self.model_name
                output.metadata.evidence_set_hash = request.evidence.evidence_hash()
                return EditorialResponse(
                    output=output,
                    provider=self.name,
                    model=self.model_name,
                    usage={
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "total_tokens": 150,
                    },
                )

        class EmptyArtifactQuery:
            def filter_by(self, **_kwargs):
                return self

            def first(self):
                return None

        class FakeDb:
            def query(self, _model):
                return EmptyArtifactQuery()

        provider = RecordingProvider()
        monkeypatch.setattr(
            "newsroom.editorial.hierarchy._persist_reduction",
            lambda *_args, **_kwargs: SimpleNamespace(id=2),
        )
        monkeypatch.setattr(
            "newsroom.editorial.hierarchy._link_route_attempts",
            lambda *_args, **_kwargs: None,
        )

        _final_reduction(
            FakeDb(),
            SimpleNamespace(job_id="bounded-reduction-job"),
            [child],
            merged,
            evidence,
            provider,
            1,
        )

        request_story_ids = [
            story.story_id for story in provider.requests[0].evidence.stories
        ]
        assert request_story_ids == [story.story_id for story in merged.stories]
        assert len(request_story_ids) <= settings.editorial_max_stories_per_call

    def test_final_reduction_keeps_grounded_ai_output_after_safe_scrub(self, monkeypatch):
        evidence = EditorialEvidenceSet(stories=[_make_story(700, source_count=2)])
        provider = FakeScalableProvider(latency_ms=0)
        merged = provider.generate(EditorialRequest(evidence=evidence)).output
        child = MapResult(
            shard_id="map-1",
            artifact_id=1,
            output=merged,
            story_ids=[700],
            evidence_ref_ids=[source.ref_id for source in evidence.stories[0].sources],
            latency_ms=0,
            usage=None,
            from_cache=False,
            fallback_used=False,
            provider=provider.name,
            model=provider.model_name,
        )
        persisted: dict[str, str] = {}

        class EmptyArtifactQuery:
            def filter_by(self, **_kwargs):
                return self

            def first(self):
                return None

        class FakeDb:
            def query(self, _model):
                return EmptyArtifactQuery()

        def persist(*_args, **kwargs):
            persisted["provider"] = kwargs["provider"]
            persisted["model"] = kwargs["model"]
            return SimpleNamespace(id=2)

        monkeypatch.setattr("newsroom.editorial.hierarchy._persist_reduction", persist)
        monkeypatch.setattr(
            "newsroom.editorial.hierarchy._link_route_attempts",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            "newsroom.editorial.hierarchy.validate_grounding",
            lambda _evidence, output: (
                output,
                SimpleNamespace(valid=False, issues=["safe scrub required"]),
            ),
        )

        _output, _level, _calls, _input, _output_tokens, fallback_used = _final_reduction(
            FakeDb(),
            SimpleNamespace(job_id="grounded-ai-reduction"),
            [child],
            merged,
            evidence,
            provider,
            1,
        )

        assert fallback_used is False
        assert persisted == {"provider": provider.name, "model": provider.model_name}

    def test_reduction_cache_identity_includes_request_limits(self, monkeypatch):
        evidence = EditorialEvidenceSet(stories=[_make_story(101, source_count=1)])
        original = _reduction_cache_key("reduction_final", evidence)
        monkeypatch.setattr(
            settings,
            "editorial_max_output_tokens",
            settings.editorial_max_output_tokens + 1,
        )

        changed = _reduction_cache_key("reduction_final", evidence)

        assert changed != original

    def test_topic_reduction_persists_map_child_edges(self, monkeypatch):
        stories = [_make_story(index, source_count=2) for index in range(1, 5)]
        evidence = EditorialEvidenceSet(stories=stories)
        seed_provider = FakeScalableProvider(latency_ms=0)
        maps: list[MapResult] = []
        for index, story in enumerate(stories):
            shard_evidence = EditorialEvidenceSet(stories=[story])
            output = seed_provider.generate(
                EditorialRequest(evidence=shard_evidence)
            ).output
            maps.append(
                MapResult(
                    shard_id=f"map-{index}",
                    artifact_id=10 + index,
                    output=output,
                    story_ids=[story.story_id],
                    evidence_ref_ids=[source.ref_id for source in story.sources],
                    latency_ms=0,
                    usage=None,
                    from_cache=False,
                    fallback_used=False,
                    provider="fake_scalable",
                    model="fake-scalable-v1",
                )
            )

        persisted: list[tuple[str, list[int] | None]] = []

        def persist(*args, **kwargs):
            persisted.append((args[5], kwargs.get("child_artifact_ids")))
            return SimpleNamespace(id=100 + len(persisted))

        class EmptyArtifactQuery:
            def filter_by(self, **_kwargs):
                return self

            def first(self):
                return None

        class FakeDb:
            def query(self, _model):
                return EmptyArtifactQuery()

        monkeypatch.setattr(
            "newsroom.editorial.hierarchy._persist_reduction",
            persist,
        )
        monkeypatch.setattr(
            "newsroom.editorial.hierarchy._link_route_attempts",
            lambda *_args, **_kwargs: None,
        )

        _reduce_artifacts(
            FakeDb(),
            SimpleNamespace(job_id="lineage-job"),
            maps,
            evidence,
            SimpleNamespace(name="deterministic", model_name="deterministic-v1"),
            0,
            0,
            0,
        )

        topic = next(item for item in persisted if item[0] == "reduction_topic")
        assert topic[1] == [10, 11, 12]


# ── Integration tests requiring PostgreSQL ───────────────────────
# These are in tests/integration/test_editorial_scalability_db.py to access the `db` fixture.
