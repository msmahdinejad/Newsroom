# Gate 1 — Docker Evidence

## Compose validation

**Command**: `docker compose config --quiet`
**Timestamp**: 2026-07-16T08:25:00Z
**Exit code**: 0
**Result**: Clean

## Build (cached)

**Command**: `docker compose build`
**Exit code**: 0
**Images**: 6 services built (migrate, collector, report-worker, scheduler, telegram-bot, telegram-ingestor)

## Build (no-cache)

**Command**: `docker compose build --no-cache`
**Exit code**: 0
**Result**: All 6 images built from scratch

## Service states (final)

**Command**: `docker compose ps -a --format 'table {{.Name}}\t{{.Status}}'`
**Timestamp**: 2026-07-16T08:35:00Z

| Service | Status |
|---|---|
| newsroom-postgres | Up (healthy) |
| newsroom-migrate | Exited (0) |
| newsroom-collector | Up (healthy) |
| newsroom-report-worker | Up (healthy) |
| newsroom-scheduler | Up (healthy) |
| newsroom-telegram-bot | Up (healthy) |
| newsroom-telegram-ingestor | Up (healthy) |

## Health checks

| Service | Check | Result |
|---|---|---|
| postgres | `pg_isready -U newsroom` | healthy |
| collector | `python -m newsroom.service_status collector` | `{"status": "healthy"}` |
| report-worker | `python -m newsroom.service_status report_worker` | `{"status": "healthy"}` |
| scheduler | `python -m newsroom.service_status scheduler` | `{"status": "healthy", "jobs": ["afternoon_news", "evening_news", "morning_news"]}` |
| telegram-bot | `python -m newsroom.service_status bot` | `{"status": "disabled", "feature": "telegram_bot"}` |
| telegram-ingestor | `python -m newsroom.service_status ingestor` | `{"status": "disabled", "feature": "telegram_ingestor"}` |

## Environment

- `TELEGRAM_BOT_ENABLED=false`
- `TELEGRAM_INGESTOR_ENABLED=false`
- No Telegram credentials provided
- No crash-loops
- No fake delivery/ingestion
