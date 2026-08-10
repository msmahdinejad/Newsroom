"""Scheduled pipeline collection stays bounded and respects service ownership."""

from newsroom.config import settings
from newsroom.pipeline.runner import _agent_reach_collection_kwargs, _collection_kwargs


def test_pipeline_collection_uses_configured_fair_cap(monkeypatch):
    monkeypatch.setattr(settings, "collect_limit_per_source", 7)
    monkeypatch.setattr(settings, "collect_max_sources_per_cycle", 19)
    monkeypatch.setattr(settings, "collect_source_spacing_seconds", 1.5)

    assert _collection_kwargs((11, 12)) == {
        "limit_per_source": 7,
        "max_sources": 19,
        "source_spacing_seconds": 1.5,
        "exclude_source_types": {"telegram", "x_timeline"},
        "source_ids": (11, 12),
    }
    assert _agent_reach_collection_kwargs((11, 12)) == {
        "limit_per_source": 7,
        "max_sources": 19,
        "min_source_spacing_seconds": 1.5,
        "source_ids": (11, 12),
    }
