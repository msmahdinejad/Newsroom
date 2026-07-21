# Gate 6 — Restart & Recovery Verification

## Test

Restarted the PostgreSQL container (`docker restart newsroom-postgres`)
while production data was present, then re-queried all durable state.

## State before → after restart (identical)

| State | Before | After |
|---|---|---|
| `source_inventory` rows | 1344 | 1344 |
| `sources` enabled | 1224 | 1224 |
| `raw_items` | 1000 | 1000 |
| `normalized_items` | 996 | 996 |
| `stories` | 1032 | 1032 |
| `reports` | 5 | 5 |
| `deliveries` | 4 | 4 |
| `delivery_chunks` | 4 | 4 |
| `collection_cursors` | 37 | 37 |
| scheduled cursor | (370, 339) | (370, 339) |
| last deliveries (msg IDs) | 339→[45], 338→[44], 337→[43] | identical |
| last reports (gen_method) | 370 none, 369 ai, 368 ai | identical |

## What survives a complete restart

Per the acceptance criteria — all retained:

- ✅ source registry (`sources` + `source_inventory`)
- ✅ cursors (`collection_cursors`)
- ✅ source health (`sources.health_status`, `last_success_at`, `consecutive_failures`)
- ✅ scheduler state (`apscheduler_jobs` table; jobs re-register with
  `replace_existing=True` on scheduler start)
- ✅ X access state (`x_account_state`)
- ✅ MTProto session (`telegram_sessions` named volume)
- ✅ reports (`reports`)
- ✅ delivery rows (`deliveries`, `delivery_chunks`)
- ✅ Telegram message IDs (`deliveries.message_ids`,
  `delivery_chunks.telegram_message_id`)

## Cursor survival across fresh sessions

Integration test `test_cursor_survives_fresh_session` writes a cursor in one
session and reads it in a brand-new `sessionmaker` session (simulating a
process restart) — values match exactly.

## Scheduler state survival

Integration test `test_gate6_scheduler` clears `apscheduler_jobs`, creates
the scheduler, and verifies the four `report_00/06/12/18` jobs (with coalesce
+ max_instances) persist in PostgreSQL. On scheduler restart, jobs
re-register idempotently (`replace_existing=True`).

## Post-restart Telegram commands

After the restart, the owner-restricted commands were re-verified live via
the Bot API (messages delivered to the chat):

- `/status` → message_id 49
- `/sources` → message_id 50
- `/schedule` → message_id 51

All produced correct Persian operational summaries (see GATE_6_TEST_RESULTS).
