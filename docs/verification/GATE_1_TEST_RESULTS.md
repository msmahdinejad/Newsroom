# Gate 1 — Test Results

## Test Classification

### Unit tests (DB-free, MagicMock)

**Command**: `uv run pytest tests/ -q --ignore=tests/integration`
**Location**: Host and container
**Result**: 115 passed, 0 failed, 0 skipped
**Duration**: ~24s (host), ~1.2s (container)

| File | Tests |
|---|---|
| test_cluster.py | 18 |
| test_cursors.py | 6 |
| test_dedupe.py | 14 |
| test_delivery.py | 14 |
| test_evidence.py | 13 |
| test_no_eval.py | 4 |
| test_normalize.py | 32 |
| test_sources.py | 15 |
| **Total** | **115** |

### PostgreSQL integration tests (real DB)

**Command**: `uv run pytest tests/integration -q -m integration`
**Location**: Inside application container
**Result**: 15 passed, 0 failed, 0 skipped
**Duration**: ~6s

| File | Tests | Coverage |
|---|---|---|
| test_schema_and_constraints.py | 8 | migrations, tables, unique, FK, JSONB, rollback, JobRun, delivery |
| test_lock_cross_process.py | 2 | advisory lock (busy + stale recovery) |
| test_cursors_db.py | 3 | cursor persistence, incremental, rollback |
| test_seed_and_story.py | 2 | seed idempotency, story relationships |
| **Total** | **15** |

### Container tests

**Command**: `docker exec newsroom-scheduler uv run pytest tests/ -q`
**Result**: 115 unit + 15 integration = 130 passed, 0 failed

### Ruff

**Command**: `uv run ruff check src/ tests/ scripts/run_pipeline.py scripts/cron_pipeline.py`
**Result**: All checks passed!
**Excluded**: `legacy/v1/` (quarantined, not on active path)

### MyPy

**Command**: `uv run mypy src/`
**Result**: Success: no issues found in 40 source files
**Excluded**: `legacy/v1/` (quarantined)

### Live public-source smoke tests

- RSS live collection: 54 new items from 38 sources (container collector)
- GitHub live collection: part of pipeline run
- No mock or fake data used

### Restart tests

- Scheduler stop/start: 3 jobs persisted (verified)
- Full compose down/up: all data persisted (verified)

### Failure-injection tests

- Lock busy: second pipeline gets exit_code=2 (verified)
- Stale lock recovery: connection drop releases lock (verified)

### Skipped/blocked

- Live Telegram delivery: blocked by credentials (Gate 2)
- Telegram MTProto collection: blocked by credentials (Gate 2)
- LLM editorial synthesis: not implemented (Gate 2+)
