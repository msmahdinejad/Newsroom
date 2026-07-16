# Gate 2 — Telegram Delivery Verification

## Metadata

- **Date**: 2026-07-16
- **Branch**: gate-2-telegram-delivery
- **Starting commit**: bc47f9d (gate-1-foundation)
- **Implementation commit**: feat: implement telegram output bot delivery
- **Status**: implemented, deterministic tests verified, live tests pending credentials

## Summary

Gate 2 implements a dedicated Telegram Bot API output service that safely delivers
persisted Persian reports and accepts report commands from authorized users.

The telegram-bot service is the sole Bot API polling owner. No second process
uses the same token. Hermes remains the development control plane.

## Implementation Evidence

### Migration 0003_gate2_telegram

Tables created:
- `telegram_updates` — update_id idempotency (unique index)
- `delivery_chunks` — per-chunk delivery state (unique delivery_id + chunk_index)
- `report_cursors` — scheduled delivery cursor (seeded with 'scheduled_delivery')
- `command_requests` — command idempotency (unique request_key)

Deliveries table enhanced: chat_ref, attempt_count, retry_count, error_category, parse_mode, last_send_at

Verified: `alembic_version` = `0003_gate2_telegram`

### Access Control (delivery/access.py)

- Fail-closed: empty allowlist denies everyone
- Numeric ID validation: malformed entries skipped safely
- No wildcard or allow-all mode
- Checked on every command and every callback
- Unauthorized users receive generic Persian denial with no infrastructure details

### Bot API Client (delivery/client.py)

- 12 error categories: invalid_token, unauthorized, rate_limited, network_timeout,
  server_error, malformed_response, blocked_bot, chat_not_found, message_too_long,
  invalid_formatting, duplicate_update, transient, unknown
- Permanent errors (7 categories) are not retried
- Transient errors retried with exponential backoff (capped at 30s)
- Token never logged; `redact_token()` returns only `[REDACTED]` (no fragments)

### Command Handlers (delivery/bot.py)

- `/report` — manual report from material since last scheduled delivery cursor
- `/report new` — only genuinely new material
- `/report comprehensive` — broad current report
- `/latest` — latest persisted report, no collection or regeneration
- `/help` — Persian help text with menu
- Persian inline menu: گزارش فوری, خبرهای جدید, گزارش جامع فعلی, آخرین گزارش, راهنمای گزارش‌ها

### Idempotency

- Telegram update_id persisted in `telegram_updates` (unique)
- Command requests persisted in `command_requests` (unique request_key)
- Duplicate update_ids skipped across restart
- Duplicate command taps return busy/existing result

### Rendering (delivery/render.py)

- HTML parse mode (documented and tested)
- Semantic chunking: paragraph → line → word boundaries
- Headline + explanation never split (same paragraph)
- Story + source links never split (same paragraph)
- HTML escaping for user/source-controlled text
- Configurable chunk size (default 3800, below 4096 max)
- Deterministic chunk ordering

### Delivery Persistence (delivery/telegram.py)

- Per-chunk records: delivery_id, chunk_index, telegram_message_id, status, attempt_count, error_category, sent_at
- Delivery record: report_id, chat_ref (hashed), total_chunks, delivered_chunks, message_ids, status, attempt_count, retry_count, error_category, parse_mode, last_send_at, delivered_at
- Bot Token never stored in any table

### Partial Multi-Chunk Recovery

Verified scenario (integration test):
1. Report requiring 6+ chunks
2. Chunks 1-3 send successfully
3. Chunk 4 fails with injected server error
4. Delivery persisted as partial
5. Retry resumes from chunk 4
6. Chunks 1-3 not sent again
7. All remaining chunks complete
8. All Telegram message IDs recorded
9. Final status: delivered

### Delivery Cursor Semantics

- Cursor advances only after `delivery.status == "delivered"`
- Failed generation: no advance
- Failed first chunk: no advance
- Partial delivery: no advance
- Complete confirmed delivery: advances exactly once
- Repeated confirmation: no double-advance (idempotent check)
- Manual runs do not advance the scheduled cursor

### Health Checks (service_status.py)

Disabled mode: `{"status": "disabled", "healthy": true}`
Blocked mode: `{"status": "blocked_by_credentials", "healthy": true}`
Enabled mode: checks DB connectivity, authorized users nonempty, polling alive, bot identity, last update/delivery timestamps, degraded conditions

### Concurrency Protection

- All manual report commands use the Gate 1 PostgreSQL advisory lock
- `run_pipeline()` acquires `pg_try_advisory_lock` before any work
- Manual and scheduled execution cannot run simultaneously
- Lock releases on success and failure (connection close)
