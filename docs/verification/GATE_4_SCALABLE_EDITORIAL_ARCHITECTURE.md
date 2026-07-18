# Gate 4 Scalable Editorial Architecture

## Status: VERIFIED

**Date:** 2026-07-18

## Architecture overview

The editorial system uses a hierarchical bounded map/reduce pipeline:

```
1. Deterministic candidate selection (selection.py)
2. Deterministic deduplication and story clustering (existing processing/)
3. Deterministic ranking and budget allocation (evidence_builder.py)
4. Stable partitioning into bounded editorial shards (sharding.py)
5. Per-shard AI editorial processing (hierarchy.py _process_shard)
6. Topic-level merge or reduction (hierarchy.py _reduce_artifacts)
7. Global cross-shard deduplication (hierarchy.py _merge_outputs)
8. Final report planning (hierarchy.py _merge_outputs)
9. Final bounded editorial synthesis (provider generate)
10. Final grounding and schema validation (validate_grounding, parse_and_validate)
11. Telegram rendering and delivery (pipeline/runner.py)
```

## Principle

The number of configured sources does not determine the size of a single AI prompt.
Source scale is absorbed by:

- Incremental collection (per-source cursors)
- Deterministic deduplication (content_hash, url_hash)
- Clustering (keyword similarity)
- Ranking (importance_score, novelty_score)
- Bounded evidence selection (max_stories_per_call, max_evidence_per_story, max_excerpt_length)
- Batching (stable sharding)
- Caching (compute_cache_key with editorial settings)
- Checkpointed reduction (persistent shards and artifacts)

## Key components

### Selection (`src/newsroom/editorial/selection.py`)
- `select_stories_for_report(db, mode)` — mode-aware story selection
- Excludes delivered stories for `manual_new` mode
- Returns `SelectionResult` with counts

### Sharding (`src/newsroom/editorial/sharding.py`)
- `shard_evidence_set(evidence)` — partitions evidence into bounded shards
- Each shard has a stable ID: `shard-<hash of sorted story IDs + partition version>`
- Respects effective token limits: `min(configured, provider_cap, app_safety_cap)`
- Stories never split across shards
- Oversized stories get evidence trimmed (not split)
- Token estimation: ~4 chars per token + overhead

### Hierarchy (`src/newsroom/editorial/hierarchy.py`)
- `run_hierarchical_editorial(db, story_ids, mode)` — main entry point
- Map stage: per-shard AI processing with cache check and lease acquisition
- Reduce stage: topic-grouped reduction for 3+ shards, bounded depth
- Failure isolation: failed shards fall back to deterministic, don't corrupt others
- Evidence lineage: `EditorialArtifactLineage` traces artifact → story → evidence_ref → URL

### Persistence (migration 0006)
- `editorial_jobs` — top-level job with budgets, counts, status
- `editorial_shards` — per-shard records with lease state
- `editorial_artifacts` — validated map/reduce outputs
- `editorial_artifact_lineage` — evidence traceability

## Effective limits

```
effective_limit = min(configured_limit, provider_capability, application_safety_cap)
```

| Setting | Configured | Effective |
|---------|-----------|-----------|
| max_output_tokens | 500,000 | 8,192 (capped) |
| shard_input_token_limit | 8,000 | 8,000 |
| shard_output_token_limit | 4,000 | 4,000 (capped at 8,192) |
| max_stories_per_shard | 3 (test) / 8 (default) | 3 / 8 |
| max_map_calls_per_report | 12 | 12 |
| max_total_input_tokens_per_report | 100,000 | 100,000 |
| max_total_output_tokens_per_report | 30,000 | 30,000 |
| max_hierarchy_depth | 3 | 3 |
