# Gate 4 Capacity and Backpressure

## Status: VERIFIED

**Date:** 2026-07-18

## Capacity controls

All scalable editorial controls are in `src/newsroom/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| editorial_max_stories_per_call | 15 | Max stories in one report |
| editorial_max_evidence_per_story | 10 | Max evidence items per story |
| editorial_max_excerpt_length | 300 | Max excerpt chars |
| editorial_max_stories_per_shard | 8 | Max stories in one shard |
| editorial_max_map_calls_per_report | 12 | Max map AI calls |
| editorial_max_reduction_calls_per_report | 4 | Max reduction AI calls |
| editorial_max_hierarchy_depth | 3 | Max reduction depth |
| editorial_max_concurrent_map | 2 | Max concurrent map calls |
| editorial_max_total_input_tokens_per_report | 100,000 | Total input budget |
| editorial_max_total_output_tokens_per_report | 30,000 | Total output budget |
| editorial_shard_input_token_limit | 8,000 | Per-shard input limit |
| editorial_shard_output_token_limit | 4,000 | Per-shard output limit |
| editorial_max_pending_jobs | 3 | Max pending editorial jobs |
| editorial_stale_job_timeout_seconds | 600 | Stale job timeout |
| editorial_scheduled_run_budget | 1 | Scheduled calls per run |
| editorial_manual_run_budget | 3 | Manual calls per run |
| editorial_timeout_seconds | 60 | Provider timeout |
| editorial_max_retries | 2 | Retry limit |

## Effective limit enforcement

```
effective_limit = min(configured_limit, provider_capability, application_safety_cap)
```

- Provider output cap: 8,192 tokens
- App safety output cap: 8,192 tokens
- App safety input cap: 128,000 tokens
- Provider min tokens: 1 (clamps non-positive values)

## Budget enforcement

In `run_hierarchical_editorial()`:
- Map calls stop when `total_model_calls >= max_map_calls_per_report`
- Map calls stop when `remaining_input < shard.estimated_input_tokens`
- Reduction depth bounded by `max_hierarchy_depth`
- Shards not processed when budget exhausted (omitted count recorded)

## Backpressure

### Bounded worker concurrency
`editorial_max_concurrent_map = 2` — limits concurrent map calls.
The current implementation processes shards sequentially (concurrency=1 effective),
with the setting available for future parallelization.

### Bounded pending jobs
`editorial_max_pending_jobs = 3` — limits queued editorial jobs.

### No duplicate scheduled job creation
Scheduled jobs use `PipelineLock` (cross-process advisory lock) — only one
pipeline runs at a time.

### Manual/scheduled lock compatibility
Both manual and scheduled runs use the same `PipelineLock`. Manual runs do not
set `NEWSROOM_SCHEDULE_LABEL`, so they don't advance the scheduled cursor.

### Rate-limit-aware pause
When the provider returns 429, the adapter retries with exponential backoff
(`min(2 * 2^attempt, 30)` seconds). The `EditorialHealth` singleton tracks
`rate_limited` and `rate_limit_until`.

### Retry backoff
Exponential: `delay = min(2.0 * (2**attempt), 30.0)` seconds.
Max retries: `editorial_max_retries = 2`.

### Stale-job recovery
`editorial_stale_job_timeout_seconds = 600` — shards with expired leases
(`lease_expires_at < now()`) can be reacquired. Tests verify this in
`test_gate4_scalable.py::TestStaleLeaseRecovery`.

### Graceful fallback
Under overload: failed shards fall back to deterministic. If all shards fail,
the final report uses deterministic output. `partial_ai = True` when some
shards fall back but not all.

## When budget is exceeded

- Prioritize deterministically (importance_score desc)
- Record omitted story and evidence counts in `EditorialJob`
- Preserve high-value official and conflicting stories (sorted first)
- No silent drop after arbitrary array index
- Low-priority candidates can be deferred to a later report
