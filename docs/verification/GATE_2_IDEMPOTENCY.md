# Gate 2 — Idempotency Verification

## Idempotency Layers

### 1. Telegram Update ID (telegram_updates table)
- Every processed update_id persisted with unique constraint
- On restart, re-delivered updates (Telegram long-polling) are detected and skipped
- Record: update_id, update_type, user_id, chat_id, command, processed_at, result

### 2. Command Request (command_requests table)
- request_key = `{mode}_{user_id}_{chat_id}`
- Same command from same user/chat within active window → returns busy or existing result
- Duplicate callback taps → idempotent (same request_key)
- Record: request_key, command, status (pending/running/ok/error/busy), report_id, delivery_id

### 3. Delivery Idempotency (deliveries table)
- Existing delivery with status="delivered" → skip re-send
- Existing delivery with status="partial" → resume from failed chunk
- Chat ID stored as SHA-256 hash (not raw)

### 4. Per-Chunk Idempotency (delivery_chunks table)
- Each chunk has unique (delivery_id, chunk_index) constraint
- Sent chunks (status="sent") are not re-sent on resume
- Failed chunks (status="failed") are retried

### 5. Cursor Idempotency (report_cursors table)
- Cursor advancement checks if already at same report_id + delivery_id
- If already advanced: no double-advance

## Test Evidence

### Idempotency tests (9 tests, all pass)
- `test_telegram_update_unique_constraint` — unique constraint on update_id
- `test_telegram_update_index` — table has correct fields
- `test_command_request_unique_constraint` — unique constraint on request_key
- `test_command_request_fields` — all required fields present
- `test_idempotency_logic_duplicate_update_skipped` — existing update → skip
- `test_idempotency_logic_new_update_processed` — new update → process
- `test_command_request_key_format` — same command+user+chat = same key
- `test_command_request_key_different_users` — different users = different keys
- `test_command_request_key_different_modes` — different modes = different keys

### Integration tests
- `test_idempotent_delivery_no_duplicate` — already-delivered report not re-sent
- `test_cursor_no_double_advance` — repeated confirmation doesn't advance twice
- `test_partial_delivery_recovery` — resume skips sent chunks 1-3

## Cross-Restart Persistence

All idempotency state is in PostgreSQL tables, not in-memory:
- `telegram_updates` survives process restart
- `command_requests` survives process restart
- `delivery_chunks` survives process restart
- `report_cursors` survives process restart

A bot restart will:
1. Resume polling from last offset + 1 (stored in memory, but Telegram drops old updates after 24h)
2. Skip any re-delivered update_ids found in `telegram_updates`
3. Resume partial deliveries from `delivery_chunks` state
4. Not re-advance cursor for already-delivered reports

## Live Verification

Status: pending credentials
