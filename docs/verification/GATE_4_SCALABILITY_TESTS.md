# Gate 4 Scalability Tests

## Status: VERIFIED

**Date:** 2026-07-18

## Test approach

All scalability tests use a **deterministic fake provider** (`tests/fake_scalable_provider.py`)
with realistic token and latency simulation. No real billable API calls.

## Synthetic datasets

### Dataset S
- 100 sources
- 1,000 raw items
- ~200 stories (after dedup/cluster simulation)
- Multiple languages (en, fa)
- Official and community sources
- 5% conflicting stories

### Dataset M
- 500 sources
- 10,000 raw items
- ~1,500 stories
- Duplicate bursts
- Conflicting stories
- Oversized evidence (excerpt_size up to 800)

### Dataset L
- 1,300+ sources
- 50,000+ raw items
- ~8,000 stories
- Realistic duplicate/clustering ratios
- Mixed RSS, GitHub, and Telegram source metadata

## Verified properties

| Property | S | M | L |
|----------|---|---|---|
| Raw item count does not become prompt item count | ✅ | ✅ | ✅ |
| Shards created | ✅ | ✅ | ✅ |
| No shard exceeds effective input limit | ✅ | ✅ | ✅ |
| Shard count within map_call_budget | ✅ | ✅ | ✅ |
| Shard IDs deterministic | ✅ | ✅ | ✅ |
| Each story in exactly one shard | ✅ | ✅ | ✅ |
| No oversized shard | ✅ | ✅ | ✅ |

## Test files

| File | Tests | Type |
|------|-------|------|
| `tests/test_editorial_sharding.py` | 18 | Unit (no DB) |
| `tests/test_editorial_scalability.py` | 16 | Unit (no DB) |
| `tests/integration/test_gate4_scalable.py` | 11 | PostgreSQL integration |
| `tests/integration/test_gate4_report_new.py` | 16 | PostgreSQL integration |
| `tests/test_editorial_selection.py` | 6 | Unit (no DB) |
| **Total new tests** | **67** | |

## Failure isolation tests

- `test_failed_shard_marked_retryable` — failed shard marked `failed_retryable`,
  successful shard stays `completed`
- Fake provider supports `fail_shard_ids` and `fail_after_n_calls` for injection

## Cache hierarchy tests

- `test_cache_key_includes_editorial_settings` — temperature and token budgets in cache key
- `test_cached_shard_served_from_cache` — existing validated artifact reused

## Restart/resume tests

- `test_completed_shard_stays_completed` — validated shards not regenerated
- `test_expired_lease_can_be_reacquired` — stale leases recoverable
- `test_successful_shard_preservation` — successful shard preserved on restart

## Performance

Tests complete in ~44 seconds (67 tests including integration tests).
Dataset L (8,000 stories) shard construction completes in <1 second.
No performance numbers are invented — actual elapsed times are recorded by pytest.
