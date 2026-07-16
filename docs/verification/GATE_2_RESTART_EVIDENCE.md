# Gate 2 — Restart Evidence

## Status: pending credentials

Restart recovery tests require live Telegram credentials to verify end-to-end behavior.

## Implemented Restart-Safe Design

### Polling Offset
- Bot stores `self._offset` in memory (last update_id + 1)
- On restart, offset resets to 0; Telegram drops updates older than 24h
- `deleteWebhook` called on startup to ensure clean polling state
- No conflict with a previous webhook or polling session

### Update Idempotency Across Restart
- `telegram_updates` table persists every processed update_id
- On restart, re-delivered updates (if any) are detected and skipped
- No duplicate processing of already-handled commands/callbacks

### Delivery Recovery Across Restart
- `deliveries` table persists partial delivery state
- `delivery_chunks` table persists per-chunk status
- On restart, `deliver_report()` finds existing partial delivery
- Resumes from first non-sent chunk (status != "sent")
- Sent chunks are not re-sent

### Cursor State Across Restart
- `report_cursors` table persists cursor position
- Cursor survives restart — no re-advancement of already-delivered reports
- Manual runs never touch the cursor

### Command Request State Across Restart
- `command_requests` table persists in-flight command status
- On restart, stale "running" requests can be detected and handled
- Already-completed commands return existing result

### Scheduler State Across Restart (Gate 1)
- APScheduler uses SQLAlchemyJobStore
- Jobs survive restart (verified in Gate 1)
- Scheduled runs use the same advisory lock as manual runs

## Planned Live Restart Tests

1. Start telegram-bot with credentials
2. Initiate a multi-chunk delivery
3. Kill telegram-bot mid-delivery (after some chunks sent)
4. Restart telegram-bot
5. Verify partial delivery resumes (sent chunks not re-sent)
6. Verify /latest returns correct report
7. Verify command idempotency: repeat a command, get existing result
8. Verify health check shows healthy after recovery
