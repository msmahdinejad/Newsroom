# Gate 4 Sharding and Reduction

## Status: VERIFIED

**Date:** 2026-07-18

## Shard construction

Shards are constructed in `src/newsroom/editorial/sharding.py`.

### Shard spec fields

Each `ShardSpec` contains:
- `shard_id` — stable hash of sorted story IDs + partition version
- `shard_sequence` — 0-based index
- `total_shards` — total shard count
- `story_ids` — ordered list of story IDs in this shard
- `evidence_ref_ids` — all evidence reference IDs in this shard
- `estimated_input_tokens` — token estimate for this shard
- `effective_input_limit` — effective input token limit
- `effective_output_limit` — effective output token limit
- `evidence_set_hash` — hash of the full evidence set

### Partitioning dimensions

Default partitioning: by importance tier + token size
- Stories ordered by `importance_score` desc, `created_at` desc
- Greedy packing: fill shard until token limit or `max_stories_per_shard`
- Each story in exactly one shard (unless omitted by budget)

### Partition determinism

Same input + same configuration → same shard IDs.
Shard ID = `sha256(partition_version:sorted_story_ids)[:16]`.

### Oversized story handling

When a single story exceeds the per-shard token budget:
- Evidence trimmed (not story split)
- High-trust sources preserved first
- Official sources prioritized
- Omitted evidence count recorded
- Conflict evidence preserved when possible
- No mid-serialization truncation

## Map/reduce hierarchy

### Map stage

Each shard is processed independently by `_process_shard()`:
1. Check cache for existing validated artifact
2. Acquire lease on shard (prevents duplicate concurrent work)
3. Call provider with shard evidence
4. Validate output schema (`parse_and_validate`)
5. Ground claims (`validate_grounding`)
6. Persist artifact + lineage
7. Update shard status to `completed`

Failed shards:
- Schema validation failure → fall back to deterministic for this shard
- Grounding failure → fall back to deterministic for this shard
- Provider timeout → fall back to deterministic
- Failed shard does NOT affect other shards

### Reduction stage

For 3+ shards: topic-grouped reduction
- Shards grouped into pairs/triples
- Each group merged via `_merge_outputs()`
- Merged artifact persisted as `reduction_topic`
- Process repeats up to `max_hierarchy_depth`
- Final reduction produces the complete `EditorialOutput`

For 1-2 shards: single reduction (or direct use for 1 shard)

### Cross-shard deduplication

`_merge_outputs()` removes duplicate stories:
- Stories tracked by `story_id` — no duplicates in final output
- Stories ranked by priority (high > medium > low) then confidence
- Limited to `max_stories_per_call` in final output

## Live verification results

| Metric | Value |
|--------|-------|
| Stories selected | 15 |
| Shards created | 5 |
| Map calls | 5 |
| Reduction calls | 1 |
| Total model calls | 6 |
| Reduction depth | 2 |
| Input tokens | 20,567 |
| Output tokens | 7,722 |
| Fallback shards | 0 |
| Cache hits | 0 |
| Telegram chunks | 2 |
| Telegram message IDs | [38, 39] |
