# Gate 0 — Recommended Next Gate

## Gate 1 Recommendation: Stabilization and Integration Testing

Gate 0 verified that the V2 rebuild has a solid foundation: Docker builds, migrations work, 105 unit tests pass, live RSS/GitHub collection works, and the pipeline generates Persian reports end-to-end. However, several critical gaps prevent production readiness.

## Prerequisites for Gate 1

### Required before any further work

1. **Remove V1 dead code** (R-02)
   - Delete or archive: src/newsroom/editorial/hermes.py, src/newsroom/digest/preview.py, src/newsroom/delivery/bot_commands.py
   - These files reference non-existent models (Digest, story.source_urls) and contain eval()
   - Risk: if imported accidentally, they crash or execute eval() on arbitrary data

2. **Fix test lint errors** (R-10)
   - `ruff check tests/` has 7 errors
   - Either fix or document the exclusion

3. **Fix MyPy errors in active code paths** (R-03)
   - rss.py:96 — datetime tzinfo conflict (potential runtime bug)
   - telegram.py:143 — Any return from int function
   - persian.py:65,67 — type incompatibility

## Gate 1 Scope

### 1. Cross-process pipeline lock (R-01)
Implement PostgreSQL advisory lock in `scripts/run_pipeline.py`:
- Acquire `pg_advisory_lock(hash('newsroom_pipeline'))` at start
- Release at end (including exception paths)
- All callers (bot.py, scheduler.py, cron_pipeline.py) inherit the lock
- Test: verify two concurrent pipeline runs don't overlap

### 2. Integration test suite (R-06)
Add tests that run against a real PostgreSQL:
- Use Docker Compose to spin up a test DB
- Test: migration from scratch creates 13 tables
- Test: pipeline run produces a report
- Test: deduplication with real DB queries
- Test: clustering with real DB queries
- Test: delivery record creation and idempotency

### 3. Collection cursor implementation (R-04)
- Add cursor read/write to RSSCollector and GitHubCollector
- Store last_seen item ID/timestamp per source
- Use cursor for incremental collection (skip already-seen items)
- Wire cursors to "report new" mode (only items since last cursor)

### 4. Scheduler persistence (R-05)
- Configure APScheduler with SQLAlchemyJobStore
- Verify jobs survive restart
- Test: stop scheduler, start again, confirm jobs are restored

### 5. Fix run_pipeline.py asyncio pattern (R-08)
- Combine `deliver_report` and `close` into single asyncio.run() call
- Verify delivery works with a mock Telegram API

### 6. Full-stack Docker test (R-53)
- Start all 6 services
- Verify each service starts and reaches healthy state
- Verify collector collects, report-worker processes, scheduler schedules
- Requires: TELEGRAM_BOT_TOKEN (or mock) for telegram-bot service

## Deferred to Gate 2+

- **LLM editorial synthesis** — Interface formalization, API integration, prompt injection testing
- **Telegram MTProto collection** — Requires credentials, one-time auth flow
- **Telegram live delivery** — Requires bot token, end-to-end test
- **Agent-Reach evaluation** — No code exists yet
- **WorldMonitor integration** — No code exists yet
- **Data retention enforcement** — Config exists, no enforcement code

## Gate 1 Success Criteria

1. No dead V1 code in the repository
2. `ruff check src/ tests/` passes clean
3. `mypy src/` passes with 0 errors on active code paths
4. PostgreSQL advisory lock prevents concurrent pipeline runs (tested)
5. Integration test suite passes against real PostgreSQL
6. Collection cursors are read and written (tested)
7. Scheduler jobs persist across restart (tested)
8. Full Docker stack starts and all services reach healthy state
9. 105+ tests pass (original unit tests + new integration tests)

## Exact Branch and Commit

- **Audit branch**: newsroom-v2-resume
- **Baseline tag**: baseline-before-resume at 57a0028
- **Gate 0 audit commit**: (created below)
- **Gate 1 should branch from**: newsroom-v2-resume after Gate 0 commit
