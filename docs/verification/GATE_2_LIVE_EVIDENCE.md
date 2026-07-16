# Gate 2 — Live Telegram Evidence

## Status: pending credentials

Live Telegram tests have not been executed because credentials have not yet been provided.

All credential-independent implementation, deterministic tests, redaction, and health behavior are complete.

## Prerequisites for Live Testing

1. TELEGRAM_BOT_TOKEN — from BotFather
2. TELEGRAM_AUTHORIZED_USER_IDS — numeric Telegram user ID(s)
3. TELEGRAM_CHAT_ID — optional, inferred from authorized incoming message

## Planned Live Acceptance Tests

### Identity and Authorization
1. Bot API identity succeeds (getMe)
2. Authorized user can use /help
3. Unauthorized user denied without operational details
4. Unauthorized callback denied
5. Bot restart preserves access-control behavior

### Existing Report Retrieval
6. /latest returns latest persisted report
7. /latest does not trigger collection or generation
8. Source links are usable
9. Persian formatting is readable

### Manual Report Commands
10. /report creates and delivers a report
11. /report new follows delivered-item semantics
12. /report comprehensive creates broad report
13. Repeated command delivery does not create duplicate runs
14. Rapid callback taps remain idempotent
15. Concurrent manual and scheduled simulation respects PostgreSQL lock

### Multi-Chunk Delivery
16. Deliver real long Persian report requiring multiple chunks
17. Record every Telegram message ID
18. Verify chunk ordering
19. Verify no broken formatting
20. Execute partial-failure recovery
21. Verify successful chunks were not duplicated

### Restart
22. Restart telegram-bot
23. Verify pending or partial delivery recovery
24. Verify /latest
25. Verify command idempotency survives restart
26. Verify full stack remains healthy

### Persistence
27. Query delivery and job records
28. Verify complete delivery confirmation
29. Verify failed/partial attempt history remains auditable
30. Verify no Token or private credential in rows or logs

## Evidence Format

Each live evidence item will include:
- Timestamp
- Command or test
- Redacted result
- Report ID
- Delivery ID
- Telegram message IDs (where relevant)
- Database state
- Passed/failed/skipped/blocked status
