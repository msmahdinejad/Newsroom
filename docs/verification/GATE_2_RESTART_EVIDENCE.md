# Gate 2 — Restart Evidence (Live)

## Date: 2026-07-16

## Test 1: Bot kill and restart

| Step | Result |
|---|---|
| Bot process killed (pid 37408) | terminated |
| Bot restarted (pid 55112) | polling resumed |
| deleteWebhook on startup | ok (no competing webhook) |
| getUpdates | 200 OK (no 409 Conflict) |
| getMe identity | @newsroom_telegram_bot id=8836543935 |

## Test 2: Idempotency survives restart

| Update ID | First Process | After Restart |
|---|---|---|
| 489846382 (/help) | processed: ok | skipped (already processed) |
| 999900300 (/latest) | — | processed: ok |

No duplicate update records created.

## Test 3: /latest after restart

Result: ok. Latest report delivered to chat.

## Test 4: Delivery state persistence

| Delivery ID | Report ID | Status | Chunks | Persisted |
|---|---|---|---|---|
| 72 | 79 | delivered | 1/1 | True |
| 71 | 78 | failed | 0/1 | True |
| 70 | 77 | delivered | 5/5 | True |
| 69 | 75 | delivered | 5/5 | True |
| 68 | 73 | delivered | 1/1 | True |
| 67 | 72 | delivered | 1/1 | True |
| 66 | 71 | delivered | 1/1 | True |

All delivery records and per-chunk state survived restart.

## Test 5: Full-stack health

Bot health status: enabled, polling alive, DB connectivity ok.
