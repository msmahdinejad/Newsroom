# Gate 1 — Restart and Recovery Evidence

## Full compose shutdown

**Command**: `docker compose down`
**Exit code**: 0
**Containers removed**: all 7 (postgres, migrate, collector, report-worker, scheduler, telegram-bot, telegram-ingestor)
**Volume preserved**: `postgres_data` (not removed)

## Full compose startup

**Command**: `docker compose up -d` (with `TELEGRAM_BOT_ENABLED=false TELEGRAM_INGESTOR_ENABLED=false`)
**Exit code**: 0

## Post-restart service states

| Service | Status | Healthy |
|---|---|---|
| newsroom-postgres | Up | healthy |
| newsroom-migrate | Exited (0) | — |
| newsroom-collector | Up | healthy |
| newsroom-report-worker | Up | healthy |
| newsroom-scheduler | Up | healthy |
| newsroom-telegram-bot | Up | healthy |
| newsroom-telegram-ingestor | Up | healthy |

## Data persistence after restart

| Table | Before shutdown | After startup |
|---|---|---|
| sources | 39 | 39 |
| raw_items | 600 | 600 |
| reports | 4 | 4 |
| collection_cursors | 36 | 36 |
| apscheduler_jobs | 3 | 3 |

## Individual service restarts

### Scheduler restart
- Stop → start
- 3 jobs persisted in `apscheduler_jobs`
- Health: `{"status": "healthy", "jobs": [...]}`

### Collector restart
- Runs collection on startup, then idles
- Health: `{"status": "healthy"}`

### Report-worker restart
- Runs processing on startup, then idles
- Health: `{"status": "healthy"}`

### Postgres restart
- Docker Desktop restart recovered all containers
- Data persisted in volume

## Backup

**Command**: `docker exec newsroom-postgres pg_dump -U newsroom -d newsroom`
**Size**: 7,161,441 bytes

## Restore (disposable database)

**Command**: `createdb newsroom_restore_test && psql < backup.sql`
**Result**: All row counts match (sources=39, raw_items=600, reports=4, cursors=36, apscheduler=3)
**Cleanup**: `DROP DATABASE newsroom_restore_test`
