# Gate 4 Test Results

## Qwen Code verification (2026-07-18)

### Full test suite: 467 passed (103.30s)

| Category | Count | File |
|----------|-------|------|
| Editorial deterministic tests | 50 | `tests/test_editorial.py` |
| Editorial adapter tests | 53 | `tests/test_editorial_adapter.py` |
| Editorial selection unit tests | 6 | `tests/test_editorial_selection.py` |
| Editorial sharding unit tests | 18 | `tests/test_editorial_sharding.py` |
| Editorial scalability unit tests | 16 | `tests/test_editorial_scalability.py` |
| PostgreSQL editorial integration tests | 17 | `tests/integration/test_gate4_editorial.py` |
| PostgreSQL report-new integration tests | 16 | `tests/integration/test_gate4_report_new.py` |
| PostgreSQL scalable integration tests | 11 | `tests/integration/test_gate4_scalable.py` |
| Other integration tests | 43 | `tests/integration/test_*.py` |
| Unit tests (Gates 0-3) | 237 | `tests/test_*.py` |
| **Total** | **467** | |

### New tests added (67)

| File | Tests | Coverage |
|------|-------|----------|
| `tests/test_editorial_selection.py` | 6 | detect_material_change unit tests |
| `tests/test_editorial_sharding.py` | 18 | Shard ID stability, token limits, oversized stories, determinism |
| `tests/test_editorial_scalability.py` | 16 | Datasets S/M/L shard construction |
| `tests/integration/test_gate4_report_new.py` | 16 | Delivered-story exclusion, material change, no-new-items |
| `tests/integration/test_gate4_scalable.py` | 11 | Job/shard persistence, lease, restart, failed-shard retry |

### Editorial deterministic tests: 50 passed

File: `tests/test_editorial.py`

### Editorial adapter tests: 53 passed

File: `tests/test_editorial_adapter.py`

### PostgreSQL integration tests: 44 passed (17+16+11)

Files: `tests/integration/test_gate4_*.py`

### Lint and type checking

- **Ruff:** All checks passed (src/, tests/, scripts/)
- **MyPy:** Success: no issues found in 63 source files
- **Compose config:** Valid

### Live provider verification

- **Minimal call:** SUCCESS — gemini-3.1-flash-lite, 2,296 tokens
- **11-scenario evaluation:** 7 live calls + 4 grounding tests — all passed
- **Focused live multi-shard:** 5 shards, 6 model calls, delivered via Telegram
- **Total live tokens:** ~52,350 across all live tests

### Known limitations

1. `/report new` now correctly excludes delivered stories (FIXED)
2. Command-level idempotency is permanent (non-expiring) — documented, not changed
3. Production capacity is bounded by configuration, not unlimited
