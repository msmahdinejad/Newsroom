# Gate 2 — Live Telegram Evidence

## Date: 2026-07-16
## Branch: gate-2-telegram-delivery
## Commit: 0c83018 (pre-live) → live-verified

## Bot Identity

| Timestamp | Action | Result | Bot Username | Bot ID |
|---|---|---|---|---|
| 2026-07-16T17:41:20+0330 | getMe | passed | @newsroom_telegram_bot | 8836543935 |
| 2026-07-16T17:41:20+0330 | deleteWebhook | passed | — | — |
| 2026-07-16T17:41:20+0330 | getUpdates | passed (no 409) | — | — |

Token display: [REDACTED]

## Authorization

| Timestamp | Update ID | User ID | Command | Result |
|---|---|---|---|---|
| 2026-07-16T14:14:18 | 489846381 | [REDACTED] | /start | ok (authorized) |
| 2026-07-16T14:19:23 | 489846382 | [REDACTED] | /help | ok (authorized) |
| 2026-07-16T14:28:34 | 999900099 | 777777777 | /help | denied (unauthorized) |

Unauthorized denial: no infrastructure details exposed.

## Commands

| Timestamp | Update ID | Command | Result | Report ID | Delivery ID | Msg IDs |
|---|---|---|---|---|---|---|
| 2026-07-16T14:19:23 | 489846382 | /help | passed | — | — | — |
| 2026-07-16T14:19:37 | 489846383 | /latest | passed | — | — | — |
| 2026-07-16T14:20:28 | 489846384 | /report | passed | 71 | 66 | [11] |
| 2026-07-16T14:34:44 | 999900100 | /report new | passed | 72 | 67 | [14] |
| 2026-07-16T14:36:23 | 999900101 | /report comprehensive | passed | 73 | 68 | [17] |
| 2026-07-16T14:34:46 | 999900102 | callback:latest | passed | — | — | — |

## Persian Inline Buttons

Button `latest` (آخرین گزارش) dispatched as callback — result: ok.

## Idempotency

| Test | Update ID | Result |
|---|---|---|
| Replay /report new | 999900100 | skipped (already processed) |
| Replay callback latest | 999900102 | skipped (already processed) |
| No duplicate reports | — | True (report 72 has 1 delivery) |
| No duplicate command requests | — | True (1 request for manual_new) |
| All update_ids distinct | — | True (8 updates, 8 distinct IDs) |

## PostgreSQL Pipeline Locking

| Test | Lock State | Result |
|---|---|---|
| Lock held + /report | held by test | result=busy, cmd_status=busy |
| Lock released + /report | free | result=ok |

## Multi-chunk Delivery

| Report ID | Chunks | Status | Message IDs |
|---|---|---|---|
| 75 | 5 | delivered | [23, 24, 25, 26, 27] |

All chunks ordered 0→4, all status=sent.

## Partial Delivery Recovery

| Phase | Delivery ID | Status | Chunks | Message IDs |
|---|---|---|---|---|
| Initial (chunks 0-2 sent, 3 failed) | 70 | partial | 3/5 | [28, 29, 30] |
| Retry (chunks 3-4 sent) | 70 | delivered | 5/5 | [28, 29, 30, 31, 32] |

Early chunks preserved: True (msg_ids 28,29,30 unchanged).
Full recovery: True.

## Cursor Semantics

| Test | Cursor Before | Cursor After | Result |
|---|---|---|---|
| Failed delivery | None | None | not advanced |
| Partial delivery | None | None | not advanced |
| Complete delivery | None | report_id=79 | advanced |
| Double confirmation | report_id=79 | report_id=79 | not double-advanced |
| Manual reports | None | None | never advanced |

## Restart Recovery

| Test | Result |
|---|---|
| Bot killed and restarted | polling resumed, no 409 |
| Replayed update 489846382 | skipped (no duplicate) |
| /latest after restart | ok |
| Delivery state persisted | 7 deliveries with correct state |

## Security

| Surface | Token Found |
|---|---|
| Git history | only synthetic test fixtures |
| Tracked files | only synthetic test fixtures |
| .env tracked | False |
| Database rows | 0 |
| Logs | 0 |
| Evidence docs | 0 |
| .dockerignore | excludes .env |
