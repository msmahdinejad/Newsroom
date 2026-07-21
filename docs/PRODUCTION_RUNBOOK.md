# Production Runbook — Persian AI Newsroom (Gate 6)

Single source of truth for operating the production newsroom. No manual
database or YAML editing is required for any task below — all operations use
the CLI or Docker Compose.

## 1. Production startup (one command)

```powershell
.\scripts\up-production.ps1
# equivalent to: docker compose up -d --wait
```

Starts: PostgreSQL, migrations, scheduler (00/06/12/18 Tehran), collector
(native RSS / GitHub / Telegram-MTProto / Reddit / web_page / YouTube in a
bounded loop), Agent-Reach worker, editorial report-worker, Telegram
ingestor, Telegram output bot. Persistent named volumes, health checks,
and `restart: unless-stopped` are configured.

## 2. First-time source inventory (one command, no DB/YAML editing)

```powershell
uv run newsroom sources reconcile   # import + activate the workbook
uv run newsroom sources status      # print reconciliation summary
```

`sources reconcile` locates the workbook (`tech_ai_programming_source_radar_global_2026*.xlsx`
in repo root / `config/import` / `~/OneDrive/Desktop`), copies it to
`config/import/source-radar.xlsx`, imports all rows into `source_inventory`,
and activates accessible sources into the `sources` registry. Idempotent —
re-running creates no duplicates.

## 3. Shutdown

```powershell
docker compose down       # stop services, keep volumes
```

## 4. Restart / recovery

```powershell
docker compose up -d --wait
```

A complete restart retains (verified): source registry, cursors, source
health, scheduler state (`apscheduler_jobs`), X access state, MTProto
session (volume `telegram_sessions`), reports, deliveries, and Telegram
message IDs — all in PostgreSQL / named volumes.

## 5. Source inventory re-import

```powershell
uv run newsroom sources import      # re-parse workbook (idempotent)
uv run newsroom sources activate    # re-evaluate accessibility
```

Re-import updates workbook metadata but preserves activation links and
historical items. Disabling a source never removes its raw items.

## 6. Source validation (bounded collection attempt)

```powershell
uv run python scripts\gate6_live_verification.py   # one source per platform
uv run python scripts\gate6_bounded_collection.py  # capped per-platform pass
```

## 7. Manual collection

```powershell
uv run newsroom collect --source-type rss          # one platform type
uv run newsroom collect                             # all enabled sources
```

## 8. Scheduled-style report trigger

```powershell
uv run newsroom pipeline run                       # full pipeline + deliver
# force a scheduled-style run that advances the delivery cursor:
$env:NEWSROOM_REPORT_MODE="scheduled"; $env:NEWSROOM_SCHEDULE_LABEL="18:00"; uv run newsroom pipeline run
```

## 9. Health inspection

```powershell
uv run newsroom health
docker compose ps
# In Telegram (owner): /status /sources /schedule
```

## 10. Failed-source inspection

```sql
-- via the CLI status, or query safely (no secrets):
SELECT name, type, platform, health_status, consecutive_failures,
       left(last_error,120) AS last_error, inactive_reason
FROM sources WHERE enabled = true AND health_status IN ('degraded','unavailable')
ORDER BY consecutive_failures DESC;
```

## 11. Delivery retry

Re-running the pipeline for the same window resumes undelivered chunks
(per-chunk state in `delivery_chunks`). The scheduled cursor advances **only
after complete delivery**.

```powershell
uv run newsroom pipeline run
```

## 12. Database backup and restore

```powershell
.\scripts\backup.ps1    # pg_dump to ./backups
.\scripts\restore.ps1   # restore from a backup file
```

## 13. Access-value rotation procedures

- **Telegram Bot token**: change `TELEGRAM_BOT_TOKEN` in `.env`, then
  `docker compose up -d --force-recreate telegram-bot`. Never committed.
- **Telegram MTProto**: re-authorize with `docker compose run --rm telegram-authorize`
  (interactive login code + optional 2FA). Session lives in the
  `telegram_sessions` volume, never in the repo.
- **Editorial AI key**: change `EDITORIAL_API_KEY` in `.env`, recreate the
  scheduler service. Never committed or logged (redacting filter scrubs it).
- **X / Twitter auth** (`TWITTER_AUTH_TOKEN`, `TWITTER_CT0`): rotate in the
  host environment; stored only in env, never in the DB or logs.

## Operational constraints (measured)

- Sources: 1344 inventory rows; 1185 active collectors; 159 inactive
  (144 X-auth, 9 access-required communities, 4 duplicates, 2 non-repo
  GitHub). Bounded concurrency `COLLECT_CONCURRENCY=4`, `COLLECT_LIMIT_PER_SOURCE=10`.
- Telegram MTProto ingestion requires outbound connectivity to Telegram DCs;
  refused connections are recorded as degraded (a failed source does not
  interrupt other collectors).
- Agent-Reach (yt-dlp / twitter-cli) is disabled by default; native RSS-based
  YouTube and native Reddit/web collectors run without it.
- Editorial AI: hierarchical sharding, bounded token/call budgets, fallback
  to deterministic on provider failure (the live acceptance report used the
  real AI provider with no fallback).
