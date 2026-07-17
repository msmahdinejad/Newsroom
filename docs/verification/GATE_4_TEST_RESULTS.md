# Gate 4 Test Results

## Qwen Code verification (2026-07-17)

### Full test suite: 400 passed (45.72s)

| Category | Count | File |
|----------|-------|------|
| Editorial deterministic tests | 50 | `tests/test_editorial.py` |
| Editorial adapter tests | 53 | `tests/test_editorial_adapter.py` |
| PostgreSQL editorial integration tests | 17 | `tests/integration/test_gate4_editorial.py` |
| Other integration tests | 43 | `tests/integration/test_*.py` |
| Unit tests (Gates 0-3) | 237 | `tests/test_*.py` |
| **Total** | **400** | |

### Editorial deterministic tests: 50 passed

File: `tests/test_editorial.py`

Coverage: editorial disabled, missing config, deterministic fallback, valid structured
response, malformed JSON, missing fields, unknown story/evidence IDs, invented URLs,
unsupported claims (numbers, dates, versions), conflicting evidence, community rumor,
official source, prompt injection, fake system messages, JSON delimiters, excessive
input/output, timeout, retry limit, rate limit, provider outage, safety refusal,
malformed structured response, cache key determinism, invalidation, Persian Unicode,
RTL, Telegram-safe rendering, no CoT storage, schema versioning.

### Editorial adapter tests: 53 passed (NEW)

File: `tests/test_editorial_adapter.py`

Coverage: URL construction safety (6 tests), effective token limits (10 tests),
request contract — endpoint, no-tools, response format, auth header, effective tokens (5 tests),
retry policy — 5xx, 429, 401, 400, max retries (5 tests), response parsing — valid JSON,
markdown fences, prose before JSON, truncated, empty, no choices, content filter, length,
unknown fields, usage parsing, no usage, metadata enforcement (12 tests), config safety (6 tests),
structured output edge cases — multiple JSON, schema failure, malformed, no CoT (4 tests),
Persian digit grounding (3 tests), cache key with report_mode and editorial settings (4 tests).

### PostgreSQL integration tests: 17 passed

File: `tests/integration/test_gate4_editorial.py`

Coverage: attempt persistence, prompt version, evidence-set hash, structured output,
claim-to-evidence refs, cache key unique, cache reuse, validation failure, fallback,
report linkage, no API key in attempt, no API key in output, transaction rollback,
health singleton, health updated, report mode persisted.

### Lint and type checking

- **Ruff:** All checks passed (src/, tests/, scripts/)
- **MyPy:** Success: no issues found in 59 source files
- **Compose config:** Valid (all 17 EDITORIAL_* vars forwarded)

### Live provider verification

- **Minimal call:** SUCCESS — gemini-3.1-flash-lite, 2,296 tokens
- **11-scenario evaluation:** 7 live calls + 4 grounding tests — all passed
- **Total live tokens:** 19,061 (13,090 prompt + 5,971 completion)
- **Total live calls:** 8

### Known limitations

1. `/report new` mode does not filter out already-delivered stories — the scheduled cursor
   is written but never read for story selection. All modes select the same 30 most-recent
   stories. This is a pre-existing design limitation, not a Gate 4 regression.
2. Command-level idempotency (`CommandRequest.request_key`) is permanent (non-expiring).
   A repeated `/report` from the same user/chat returns the previously generated report
   indefinitely rather than generating a fresh one.
