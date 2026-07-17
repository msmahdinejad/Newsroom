# Gate 3 Test Results

**Date**: 2026-07-17
**Commit**: latest

## Deterministic Tests

### test_telegram_deterministic.py (31 tests)
- Disabled service without credentials: PASS
- Enabled but missing credentials: PASS
- Enabled with all credentials: PASS
- Canonical session path default: PASS
- .env.example has canonical names: PASS
- No login code or 2FA in .env.example: PASS
- Session excluded from git: PASS
- Session excluded from docker: PASS
- Session path in compose volume: PASS
- Permalink public channel: PASS
- Permalink strips @ prefix: PASS
- Permalink strips t.me prefix: PASS
- Permalink none username: PASS
- Permalink no message id: PASS
- Extract links from text: PASS
- Extract links dedup: PASS
- Extract links empty: PASS
- Content hash deterministic: PASS
- Content hash channel specific: PASS
- Content hash message specific: PASS
- Adapt basic message: PASS
- Adapt to_dict serializable: PASS
- Adapt edited message: PASS
- Prompt injection remains inert data: PASS
- Prompt injection outbound links not executed: PASS
- Cursor filter drops older: PASS
- Cursor advance: PASS
- Cursor no advance on empty: PASS
- FloodWait persists state: PASS
- FloodWait classification recoverable: PASS
- No eval in telegram sources: PASS

### test_telegram_persistence.py (16 tests)
- First collection persists new items: PASS
- Incremental collection skips existing: PASS
- Overlapping remains idempotent: PASS
- No new message run: PASS
- Duplicate update same content hash skipped: PASS
- Edited message updates in place: PASS
- Late arriving message accepted: PASS
- Cursor advances after persist: PASS
- Cursor isolation between sources: PASS
- Gap detection finds missing: PASS
- No gap when contiguous: PASS
- Mark deleted sets flag: PASS
- Mark deleted nonexistent returns false: PASS
- One channel failure doesn't stop others: PASS
- Health transition to healthy after success: PASS
- Multi-channel failure isolation: PASS

## PostgreSQL Integration Tests

### test_gate3_mtproto.py (15 tests)
- Gate3 tables exist: PASS
- Telegram channels unique ID: PASS
- Raw items telegram identity unique: PASS
- Alembic at gate3 revision: PASS
- Channel source persisted: PASS
- Unique telegram channel ID: PASS
- Username update no duplicate source: PASS
- Message identity constraint: PASS
- Cursor persistence: PASS
- Edit updates existing item: PASS
- Forward attribution persisted: PASS
- Gap record persisted: PASS
- Health state transitions: PASS
- Restart continues from cursor: PASS
- Transaction rollback on failure: PASS

## Summary
- Deterministic: 47/47 PASS
- Integration: 15/15 PASS
- Total: 62/62 PASS
- Ruff: clean
- Gate 2 tests: 239/239 PASS (no regression)
