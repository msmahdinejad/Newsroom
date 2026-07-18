# Gate 4 Restart and Idempotency

## Status: VERIFIED

**Date:** 2026-07-18 (updated for scalable editorial)

## Cache key computation

Location: `src/newsroom/editorial/persistence.py` → `compute_cache_key()`

```python
cache_key = SHA256(f"{report_mode}:{evidence_hash}:{prompt_version}:{provider}:{model}"
                   f":t{temperature}:mi{max_input_tokens}:mo{max_output_tokens}")
```

Same (mode, evidence, prompt, provider, model, generation settings) = same cache key.

## Cache key includes editorial generation settings

The cache key now includes `temperature`, `max_input_tokens`, and `max_output_tokens`.
This ensures that changes to generation settings invalidate the cache, preventing stale
editorial results from being returned when the owner changes temperature or token budgets.

Tests: `test_cache_key_includes_editorial_settings` (3 assertions in `tests/test_editorial_adapter.py`)

## Cache reuse

- `find_cached_attempt(db, cache_key)` returns existing accepted attempt
- `orchestrator._check_cache()` now calls `find_cached_attempt()` (previously a stub returning None)
- Duplicate bot callbacks do not create duplicate model calls
- Completed accepted outputs are not regenerated unnecessarily
- The cache key is stored as a unique index in `editorial_attempts.cache_key`

## Cache invalidation

| Change | Invalidates? | Via |
|--------|-------------|-----|
| Evidence change | Yes | evidence_hash changes |
| Prompt-version change | Yes | prompt_version in key |
| Model change | Yes | model in key |
| Report mode change | Yes | report_mode in key |
| Provider change | Yes | provider in key |
| Temperature change | Yes | temperature in key (NEW) |
| Max input tokens change | Yes | max_input_tokens in key (NEW) |
| Max output tokens change | Yes | max_output_tokens in key (NEW) |

## Restart safety

- Editorial attempt is persisted with `started_at` and `completed_at`
- If the process restarts during generation, the attempt has no `completed_at`
- The cache key uniqueness prevents duplicate accepted attempts
- Failed outputs may be retried according to policy
- Accepted editorial reports remain retrievable via `/latest`

## Idempotent editorial identity

The `editorial_attempts` table stores:
- `evidence_set_hash`: identifies the exact evidence used
- `prompt_version`: identifies the prompt version
- `provider` + `model`: identifies the AI model
- `cache_key`: unique identity for the editorial result
- `report_mode`: persisted (fixed from prior stub `""`)

## Report modes — verification

| Requirement | Status |
|-------------|--------|
| `/latest` causes zero provider calls | VERIFIED — pure DB read, no pipeline/orchestrator call |
| `/report new` avoids delivered material | KNOWN LIMITATION — cursor written but not read for selection |
| `/report comprehensive` includes recent material | VERIFIED (trivially — same selection as all modes) |
| Manual reports don't corrupt scheduled cursor | VERIFIED — cursor_key=None when no SCHEDULE_LABEL |
| Duplicate updates make no duplicate provider calls | VERIFIED — TelegramUpdate + cache check |
| Duplicate callbacks reuse idempotency records | VERIFIED — CommandRequest + editorial cache |
| Cache identity includes all required fields | VERIFIED — mode, evidence hash, prompt, provider, model, temperature, token budgets |

## Known limitation: `/report new`

**FIXED (2026-07-18):** The `/report new` mode now correctly excludes stories from
successfully delivered reports. See `GATE_4_REPORT_NEW_SEMANTICS.md` for details.
The scheduled cursor is still written for scheduled delivery tracking, but story
selection for `manual_new` mode now uses the `get_delivered_story_ids()` set-based
query against `reports.story_ids` joined to `deliveries.status = 'delivered'`.

## Scalable editorial restart and resumability

### Editorial jobs, shards, and artifacts

Migration `0006_gate4_scalable` adds:
- `editorial_jobs` — top-level job with status, budgets, counts
- `editorial_shards` — per-shard records with lease state
- `editorial_artifacts` — validated map/reduce outputs
- `editorial_artifact_lineage` — evidence traceability

### Restart behavior

- ✅ Validated shards not regenerated unnecessarily (cache check in `_process_shard`)
- ✅ Failed shards may retry according to policy (`failed_retryable` status)
- ✅ Final reduction waits for required child artifacts (all shards must complete)
- ✅ Duplicate workers cannot process the same shard concurrently (unique lease)
- ✅ Accepted artifacts are reusable from cache (`cache_key` unique index)
- ✅ Stale running leases are recoverable (`lease_expires_at` check)

### Idempotency

- Editorial job `job_id` is unique — duplicate jobs rejected
- Shard `(job_db_id, shard_id)` is unique — duplicate shards rejected
- Artifact `cache_key` is unique — duplicate artifacts rejected
- Pipeline `PipelineLock` prevents concurrent pipeline runs

### Tests

- `test_completed_shard_stays_completed` — shard status preserved across restart
- `test_expired_lease_can_be_reacquired` — stale lease recovery
- `test_failed_shard_marked_retryable` — failed shard isolation
- `test_no_api_key_persisted` — no secrets in editorial tables

## Command-idempotency retention

The existing `CommandRequest` table (Gate 2) is unchanged. The permanent,
non-expiring idempotency records remain as-is. See `GATE_4_REPORT_NEW_SEMANTICS.md`
for the documented growth risk and future archival policy.
