# Gate 1 — Concurrency Evidence

## Lock implementation

PostgreSQL session-level advisory lock (`pg_try_advisory_lock`) on dedicated connection.

**Key**: `SHA-256("newsroom_report_pipeline")[:8]` as signed 64-bit integer
**Module**: `src/newsroom/pipeline/lock.py`

## Cross-process lock: busy test

**Method**: Hold lock in background container exec, run pipeline in second container exec.

**Holder**: `docker exec -d ... uv run python -c "with PipelineLock(owner='holder_bg'): time.sleep(10)"`
**Contender**: `docker exec -e NEWSROOM_JOB_ID=gate1_lock_test ... scripts/run_pipeline.py`

**Result**:
```json
{"status": "busy", "exit_code": 2, "error": "pipeline lock held by another process"}
```

Exit code 2 (deterministic busy). No waiting, no overlap.

## Stale lock recovery

**Method**: Acquire advisory lock on a connection, close connection without unlock, verify second connection can acquire.

**Result**: Lock released on connection close. Second acquisition succeeded.

## Integration test (multiprocessing)

**Test**: `tests/integration/test_lock_cross_process.py`
**Method**: `multiprocessing.Process` with `spawn` context, independent database connections.

- `test_second_connection_gets_busy`: holder acquires, contender gets `busy` — PASS
- `test_stale_lock_released_on_disconnect`: connection drop frees lock — PASS

## Pipeline run with lock

Full pipeline run inside container:
- Lock acquired: `"lock_owner": "0e5f2ed01744:218:1fcf0286"`
- All stages completed
- Lock released on completion
- Report #6 generated successfully
