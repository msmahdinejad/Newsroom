# Gate 1 — Foundation Verification

## Metadata

- **Date**: 2026-07-16
- **Branch**: gate-1-foundation
- **Starting commit**: b6f068b (Gate 0 audit)
- **Auditor**: Hermes Agent (autonomous)

## Summary

Gate 1 converts the partially verified MVP into a deterministic, database-backed, cross-process-safe, restartable Docker application. All 12 required corrections were implemented and verified.

## Corrections implemented

### 1. V1 legacy code quarantined
- `hermes.py`, `preview.py`, `bot_commands.py`, `telegram_mtproto.py` moved to `legacy/v1/`
- No active import path references them
- `eval()` eliminated from all active code
- Tests prove no active path depends on V1 fields or unsafe evaluation

### 2. One authoritative execution path
- `newsroom.pipeline.runner.run_pipeline()` is the single entrypoint
- Scheduler, CLI, bot, cron, PS wrappers all call the same function
- ADR: `docs/adr/ADR-production-execution-path.md`

### 3. `run_pipeline.py` fixed
- Single `asyncio.run()` lifecycle — no nested event loops
- One correlation ID per invocation
- Deterministic exit codes: 0 (ok), 1 (error), 2 (busy)
- Structured JSON failure reporting
- No swallowed exceptions

### 4. PostgreSQL advisory lock
- Session-level `pg_try_advisory_lock` on dedicated connection
- Cross-process: verified with independent container execs
- Crashed owner releases automatically on connection drop
- ADR: `docs/adr/ADR-pipeline-locking.md`

### 5. Collection cursors implemented
- Per-source structured JSON cursor (not opaque string)
- RSS: `last_published` + `seen_entry_ids` (last 200)
- GitHub: `last_release_id`
- Cursor advances only after successful persistence
- Overlap windows allowed; content_hash dedup makes them idempotent
- Tests: 6 unit + 3 integration

### 6. PostgreSQL integration tests
- 15 tests against real PostgreSQL 16
- Migrations, tables, constraints, JSONB, rollback, FK, unique
- Cross-process lock with multiprocessing
- Cursor persistence and rollback
- Seed idempotency, story relationships, delivery idempotency
- Run inside application container

### 7. Scheduler persistence
- APScheduler + SQLAlchemyJobStore backed by PostgreSQL
- 3 Tehran-time jobs (09:00, 15:00, 21:00)
- `replace_existing=True` — no duplicate accumulation
- `coalesce=True`, `max_instances=1`, `misfire_grace_time=300`
- Verified: jobs survive stop/start
- ADR: `docs/adr/ADR-scheduler-ownership.md`

### 8. Credential-disabled Telegram services
- `TELEGRAM_BOT_ENABLED=false` → bot idles, status `disabled`
- `TELEGRAM_INGESTOR_ENABLED=false` → ingestor idles, status `disabled`
- No network authentication attempted
- No crash-loop
- Health check distinguishes disabled from failed
- No fake delivery/ingestion recorded

### 9. Docker health checks
- postgres: `pg_isready` (built-in)
- collector: `newsroom.service_status collector` (DB check)
- report-worker: `newsroom.service_status report_worker` (DB check)
- scheduler: `newsroom.service_status scheduler` (DB + jobs table)
- telegram-bot: `newsroom.service_status bot` (disabled/enabled)
- telegram-ingestor: `newsroom.service_status ingestor` (disabled/enabled)

### 10. Linting and type checking
- Ruff: clean on src/, tests/, scripts/run_pipeline.py, scripts/cron_pipeline.py
- MyPy: 0 errors on src/ (40 source files)
- V1 quarantined files excluded from both

### 11. Full-stack restart and recovery
- Clean compose validation: pass
- Clean build: pass
- No-cache build: pass
- Migration: pass
- All services healthy: pass
- Pipeline execution: pass (report #6 generated)
- Lock busy behavior: pass (exit code 2)
- Scheduler restart: pass (3 jobs persisted)
- Full compose down/up: pass (all data persisted)
- Backup: 7,161,441 bytes
- Restore: all row counts match

### 12. Documentation synchronization
- All evidence files created under `docs/verification/`
- Three ADRs created
- No claims of production-readiness
