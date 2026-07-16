# ADR: Scheduler Ownership and Persistence

**Date**: 2026-07-16
**Status**: Accepted
**Gate**: Gate 1

## Context

Gate 0 found APScheduler used an in-memory job store. Jobs were re-created from code on each restart, not restored from DB. JobRun records tracked executions but didn't persist job definitions. Job state (pauses, modifications) was lost on restart.

## Decision

Configure APScheduler with a **SQLAlchemyJobStore** backed by PostgreSQL.

### Configuration

- `SQLAlchemyJobStore(url=DATABASE_URL)` as the default job store
- Timezone: `Asia/Tehran` (unchanged)
- Three cron jobs: 09:00, 15:00, 21:00 Tehran
- `replace_existing=True` on `add_job` — idempotent startup, no duplicate accumulation
- `coalesce=True` — multiple misfires produce one execution
- `max_instances=1` — no parallel job instances
- `misfire_grace_time=300` — 5-minute grace window

### Execution path

Scheduled jobs call `newsroom.pipeline.runner.run_pipeline` — the same function used by CLI, bot, and cron. The runner acquires the PostgreSQL advisory lock internally, so scheduler runs respect the lock.

### Persistence verification

- `apscheduler_jobs` table in PostgreSQL stores job definitions
- Jobs survive `docker compose stop/start` (verified: 3 jobs before and after)
- Health check queries `apscheduler_jobs` table directly (not a second jobstore instance)

## Consequences

- Jobs persist across container restarts
- No job accumulation on repeated startup
- Scheduler state does not depend on Hermes conversation memory
- Misfire behavior is explicit (coalesce + grace_time=300)
