# Gate 4 Delivery

## Status: PENDING

Live delivery testing is pending credential configuration.

## Delivery path

AI-edited reports use the same delivery path as deterministic reports:

1. `generate_editorial()` in `src/newsroom/editorial/orchestrator.py` produces report content
2. Pipeline runner creates a `Report` record with `generation_method = "ai"` or `"deterministic"`
3. `TelegramDelivery.deliver_report()` in `src/newsroom/delivery/telegram.py` sends the report
4. `render_report_html()` in `src/newsroom/delivery/render.py` splits into Telegram-safe chunks
5. Per-chunk delivery records are persisted with Telegram message IDs
6. Delivery cursor advances only after confirmed complete delivery (scheduled runs)

## No changes to Gate 2

The verified Gate 2 delivery service is unchanged:
- Same `TelegramBotClient` with error classification
- Same `DeliveryChunk` per-chunk state
- Same `ReportCursor` advancement semantics
- Same idempotency (already-delivered reports not re-sent)

## Report content

The editorial orchestrator's `_render_persian_report()` produces plain text
with emojis and URLs, which is then HTML-escaped and chunked by the existing
render module.
