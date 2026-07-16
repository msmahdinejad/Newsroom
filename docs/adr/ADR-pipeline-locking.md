# ADR: Pipeline Locking Strategy

**Date**: 2026-07-16
**Status**: Accepted
**Gate**: Gate 1

## Context

The Gate 0 audit identified that the pipeline lock was in-process only (`bot.py` boolean flag). Scheduler and bot containers could run the pipeline simultaneously, causing duplicate reports and inconsistent state. JobRun records were tracking rows, not locks.

## Decision

Implement a PostgreSQL **session-level advisory lock** (`pg_try_advisory_lock`) on a dedicated database connection, held for the complete pipeline duration.

### Key design

- Lock key: stable 64-bit integer derived from `SHA-256("newsroom_report_pipeline")[:8]`
- Dedicated engine with `pool_size=1, max_overflow=0` — lock lives on one connection only
- `AUTOCOMMIT` isolation so the advisory lock is session-scoped, not transaction-scoped
- `pg_try_advisory_lock` (non-blocking): second caller gets deterministic `busy` result (exit code 2)
- `pg_advisory_unlock` in `__exit__`, always followed by connection close
- Connection close (crash/exit) releases the lock automatically — no permanent lock
- Owner ID: `hostname:pid:uuid8` stored via `set_config()` for diagnostics (not a lock)

### What JobRun is NOT

JobRun records track pipeline executions for audit. They are not locks. Lock acquisition and JobRun creation happen in the same session, but the lock is on a separate connection — they cannot race.

## Alternatives considered

1. **Transactional lease table**: more complex, requires heartbeat/renewal, stale-lock recovery. Advisory lock is simpler and crash-safe.
2. **Redis distributed lock**: adds a dependency. PostgreSQL is already required.
3. **In-process lock only**: insufficient across containers.

## Consequences

- Only one pipeline run across all containers/processes at any time
- Second caller receives `{"status": "busy", "exit_code": 2}` — no waiting
- Crashed owner's connection drop releases the lock automatically
- Scheduled and manual execution conflict behavior: both get `busy` if already running
- Tests use `multiprocessing.Process` with independent connections (not threads)
