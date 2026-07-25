# Gate 0 — Risk Register

Risks ordered by severity. Each risk includes likelihood, impact, and recommended remediation.

## Critical Risks

### R-01: No cross-process pipeline lock
- **Severity**: Critical
- **Likelihood**: High (scheduler and bot run in separate containers)
- **Impact**: Concurrent pipeline runs can cause duplicate reports, data corruption, or inconsistent state
- **Evidence**: bot.py uses in-process boolean `_pipeline_lock`. scheduler.py uses `max_instances=1` per job but no inter-process lock. Both call `scripts/run_pipeline.py` independently.
- **Affected files**: src/newsroom/delivery/bot.py, src/newsroom/scheduler.py, scripts/run_pipeline.py
- **Remediation**: Implement PostgreSQL advisory lock (`pg_advisory_lock`) in run_pipeline.py. All callers (bot, scheduler, cron) acquire the lock before running.

### R-02: Dead V1 code with eval() on non-existent fields
- **Severity**: High
- **Likelihood**: Medium (dead code, but importable and callable)
- **Impact**: If hermes.py or preview.py is ever called, it will crash with AttributeError (Story has no source_urls) or execute eval() on arbitrary data
- **Evidence**: hermes.py:70 `eval(story.source_urls)`, preview.py:112 `eval(story.source_urls)`. Story model has no `source_urls` attribute. Both reference `Digest` model (renamed to `Report`).
- **Affected files**: src/newsroom/editorial/hermes.py, src/newsroom/digest/preview.py
- **Remediation**: Remove V1 dead code or move to deprecated/ archive.

### R-03: MyPy has 15 errors including type safety issues
- **Severity**: Medium
- **Likelihood**: Medium
- **Impact**: Type errors in telegram_mtproto.py (None attribute access), rss.py (datetime tzinfo conflict), telegram.py (Any return) could cause runtime failures
- **Evidence**: `uv run mypy src/` returns 15 errors in 6 files
- **Affected files**: editorial/persian.py, delivery/telegram.py, editorial/hermes.py, digest/preview.py, sources/telegram_mtproto.py, sources/rss.py
- **Remediation**: Fix type errors, especially in active code paths (rss.py, telegram.py, persian.py).

## High Risks

### R-04: Collection cursors not implemented
- **Severity**: Medium
- **Likelihood**: High (every collection cycle)
- **Impact**: No incremental collection — every run fetches all items and relies on content_hash dedup. Works for current scale but inefficient and doesn't support true "new since last" semantics for report modes.
- **Evidence**: collection_cursors table has 0 rows. No code reads or writes CollectionCursor.
- **Affected files**: All collectors, run_pipeline.py, cli/commands/collect.py
- **Remediation**: Implement cursor read/write in collectors. Use cursors for incremental collection and "report new" mode.

### R-05: Scheduler job persistence not true persistence
- **Severity**: Medium
- **Likelihood**: Low (jobs re-created from code on restart)
- **Impact**: Missed jobs during downtime are not recovered (no misfire queue beyond APScheduler's in-memory grace period). Job state (pauses, modifications) lost on restart.
- **Evidence**: scheduler.py uses AsyncIOScheduler without SQLAlchemyJobStore. JobRun records are for audit, not job restoration.
- **Affected files**: src/newsroom/scheduler.py
- **Remediation**: Configure APScheduler with SQLAlchemyJobStore backed by PostgreSQL.

### R-06: Tests don't cover integration paths
- **Severity**: Medium
- **Likelihood**: High (every test run)
- **Impact**: Pipeline bugs only caught at runtime. DB interactions, migration correctness, and multi-stage pipeline flow untested.
- **Evidence**: conftest.py explicitly states "DB-free" and uses MagicMock for all sessions. 105 tests are all unit tests.
- **Affected files**: tests/conftest.py, all test files
- **Remediation**: Add integration test suite with a real PostgreSQL instance (testcontainers or Docker Compose).

## Medium Risks

### R-07: report-worker service command is one-shot, not a worker
- **Severity**: Medium
- **Likelihood**: High (by design)
- **Impact**: `process all` runs once and exits. With `restart: unless-stopped`, the container will restart and re-run, but this is a loop, not a worker. It doesn't wait for new items.
- **Evidence**: compose.yaml command: `uv run python -m newsroom.cli.main process all`
- **Affected files**: compose.yaml, src/newsroom/cli/commands/process.py
- **Remediation**: Either make report-worker a polling daemon or document it as a batch processor triggered by scheduler.

### R-08: run_pipeline.py calls asyncio.run() twice
- **Severity**: Low-Medium
- **Likelihood**: Low (only when Telegram is configured)
- **Impact**: `asyncio.run(td.deliver_report(...))` then `asyncio.run(td.close())` creates two event loops. The httpx client from the first loop may not close properly in the second.
- **Evidence**: run_pipeline.py:220-221
- **Affected files**: scripts/run_pipeline.py
- **Remediation**: Use a single asyncio.run() with both calls.

### R-09: bot.py path construction for subprocess is fragile
- **Severity**: Low
- **Likelihood**: Medium (path-dependent)
- **Impact**: bot.py:169 constructs path relative to __file__ which may not resolve correctly in Docker container
- **Evidence**: `os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "run_pipeline.py")`
- **Affected files**: src/newsroom/delivery/bot.py
- **Remediation**: Use absolute path or PYTHONPATH-based import.

### R-10: Ruff lint errors in tests
- **Severity**: Low
- **Likelihood**: High (every lint check)
- **Impact**: Tests directory fails lint. CI may fail if lint covers tests.
- **Evidence**: `ruff check tests/` returns 7 errors
- **Affected files**: tests/test_delivery.py, tests/test_evidence.py, tests/test_sources.py
- **Remediation**: Fix lint errors or configure ruff to exclude tests.

## Low Risks

### R-11: Documentation size discrepancy
- **Severity**: Low
- **Likelihood**: Certain
- **Impact**: Minor credibility issue. Backup reported as 8.7MB, actual is 4.3MB.
- **Evidence**: VERIFICATION_REPORT says "8.7MB dump", pg_dump produces 4.3MB
- **Remediation**: Update documentation.

### R-12: bot_commands.py has hardcoded Windows path
- **Severity**: Low
- **Likelihood**: Low (dead code)
- **Impact**: If ever called outside the specific machine, will fail
- **Evidence**: the archived v1 bot used a machine-specific `PROJECT_DIR`
- **Affected files**: src/newsroom/delivery/bot_commands.py
- **Remediation**: Remove dead code.
