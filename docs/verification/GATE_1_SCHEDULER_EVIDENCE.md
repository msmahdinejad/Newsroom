# Gate 1 — Scheduler Evidence

## Implementation

**Module**: `src/newsroom/scheduler.py`
**Job store**: `SQLAlchemyJobStore` backed by PostgreSQL
**Table**: `apscheduler_jobs`

## Configuration

- **Timezone**: `Asia/Tehran`
- **Jobs**: 09:00, 15:00, 21:00 Tehran
- **Coalesce**: True (multiple misfires → one execution)
- **Max instances**: 1 per job
- **Misfire grace time**: 300 seconds
- **replace_existing**: True (idempotent startup)

## Job persistence

### After first start

```sql
SELECT id FROM apscheduler_jobs;
--
 morning_news
 afternoon_news
 evening_news
(3 rows)
```

### After stop/start

**Command**: `docker compose stop scheduler` → `docker compose start scheduler`

```
Before stop: 3 jobs in apscheduler_jobs
After start:  3 jobs in apscheduler_jobs (same IDs, same next_run_time)
```

### Health check

```
{"status": "healthy", "jobs": ["afternoon_news", "evening_news", "morning_news"]}
```

## No duplicate accumulation

Scheduler restarted multiple times. Each startup uses `replace_existing=True`. Job count remained 3 — no duplicates created.

## Scheduled execution path

Scheduled jobs call `newsroom.pipeline.runner.run_pipeline` via `asyncio.run_in_executor`. This is the same function used by CLI, bot, and cron. The pipeline runner acquires the PostgreSQL advisory lock internally.

## Independence from Hermes

Scheduler state lives entirely in PostgreSQL (`apscheduler_jobs` table). No dependency on Hermes conversation memory or host-side state.
