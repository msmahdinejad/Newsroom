# Gate 4 Restart and Idempotency

## Cache key computation

Location: `src/newsroom/editorial/persistence.py` → `compute_cache_key()`

```python
cache_key = SHA256(f"{report_mode}:{evidence_hash}:{prompt_version}:{provider}:{model}")
```

Same (mode, evidence, prompt, provider, model) = same cache key.

## Cache reuse

- `find_cached_attempt(db, cache_key)` returns existing accepted attempt
- Duplicate bot callbacks do not create duplicate model calls
- Completed accepted outputs are not regenerated unnecessarily
- The cache key is stored as a unique index in `editorial_attempts.cache_key`

## Cache invalidation

- Prompt-version change → different cache key
- Evidence change → different evidence_hash → different cache key
- Model change → different cache key
- Report mode change → different cache key

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
