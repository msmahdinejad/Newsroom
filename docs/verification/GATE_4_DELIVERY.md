# Gate 4 Delivery

## Status: VERIFIED

**Date:** 2026-07-17
**Pipeline run:** `gate4_live_delivery` (manual mode)

## Live delivery result

| Metric | Value |
|--------|-------|
| Report ID | 227 |
| Delivery ID | 205 |
| Telegram message ID | 36 |
| Chunk count | 1 |
| Generation method | ai |
| Provider | openai_compatible |
| Model | gemini-3.1-flash-lite |
| Report mode | manual |
| Editorial attempt ID | 194 |
| Editorial status | ok |
| Fallback used | false |
| Latency | 10,562 ms |
| Token usage | 10,052 total (8,557 prompt + 1,495 completion) |
| Grounding | ok |
| Validation | valid (no issues) |
| Content length | 1,512 chars |
| Secret leakage | none (no API key, no Bearer, no system prompt) |

## Delivery path

AI-edited reports use the same delivery path as deterministic reports:

1. `generate_editorial()` in `src/newsroom/editorial/orchestrator.py` produces report content
2. Pipeline runner creates a `Report` record with `generation_method = "ai"`
3. `TelegramDelivery.deliver_report()` sends the report
4. `render_report_html()` splits into Telegram-safe chunks
5. Per-chunk delivery records are persisted with Telegram message IDs
6. Delivery cursor advances only after confirmed complete delivery (scheduled runs)

## No changes to Gate 2

The verified Gate 2 delivery service is unchanged:
- Same `TelegramBotClient` with error classification
- Same `DeliveryChunk` per-chunk state
- Same `ReportCursor` advancement semantics
- Same idempotency (already-delivered reports not re-sent)

## Manual mode safety

The delivery was performed in manual mode (`NEWSROOM_REPORT_MODE=manual`):
- `NEWSROOM_SCHEDULE_LABEL` was NOT set → `cursor_key=None`
- The scheduled delivery cursor was NOT advanced
- No corruption of scheduled cursor state

## Persistence verification

All records verified in PostgreSQL:
- `reports` table: ID 227, `generation_method=ai`, `report_mode=manual`
- `editorial_attempts` table: ID 194, `provider=openai_compatible`, `model=gemini-3.1-flash-lite`, `status=ok`, `fallback_used=false`, `report_mode=manual`, cache_key present
- `deliveries` table: ID 205, `status=delivered`
- `delivery_chunks` table: ID 415, `chunk_index=0`, `telegram_message_id=36`, `status=sent`
