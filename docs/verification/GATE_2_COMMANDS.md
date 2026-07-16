# Gate 2 — Command Verification

## Required Commands

| Command | Persian Inline Button | Status |
|---|---|---|
| `/report` | گزارش فوری | implemented |
| `/report new` | خبرهای جدید | implemented |
| `/report comprehensive` | گزارش جامع فعلی | implemented |
| `/latest` | آخرین گزارش | implemented |
| `/help` | راهنمای گزارش‌ها | implemented |

## Command Behavior

### `/latest`
- Returns latest successfully persisted and delivered report
- Does NOT trigger collection or regeneration
- Queries `Delivery.status == "delivered"` joined to `Report`
- Falls back to latest report if no delivered report exists
- Renders via HTML-safe chunking

### `/report`
- Creates manual report for material since most recent scheduled-delivery cursor
- Pipeline mode: `manual`
- Does NOT advance the scheduled delivery cursor
- Uses PostgreSQL advisory lock (Gate 1)

### `/report new`
- Returns only genuinely new material not previously delivered
- Pipeline mode: `manual_new`
- Does NOT advance the scheduled delivery cursor

### `/report comprehensive`
- Creates broad current report, may include still-important recent stories
- Pipeline mode: `manual_comprehensive`
- Does NOT advance the scheduled delivery cursor

### `/help`
- Returns Persian help text with inline menu
- No secrets or infrastructure details in help text

## Manual Run Cursor Behavior

Manual report commands do NOT consume or corrupt the scheduled report cursor.
The scheduled cursor (`scheduled_delivery`) advances only when:
1. A scheduled (not manual) pipeline run produces a report
2. That report is fully delivered (all chunks confirmed)
3. The delivery status is "delivered"

Manual runs use a separate `request_key` for command idempotency but do not
touch `report_cursors`.

## Test Evidence

- `test_dispatch_help` — /help routes to menu
- `test_dispatch_start` — /start routes to menu
- `test_dispatch_latest` — /latest routes to handler
- `test_dispatch_report_now` — callback report_now → manual mode
- `test_dispatch_report_new` — callback report_new → manual_new mode
- `test_dispatch_report_comprehensive` — callback → manual_comprehensive mode
- `test_dispatch_callback_help` — callback help routes to menu
- `test_dispatch_callback_latest` — callback latest routes to handler
- `test_dispatch_unknown_shows_menu` — unknown command shows menu
- `test_menu_keyboard_has_persian_labels` — all 5 Persian labels present
- `test_menu_keyboard_callback_data` — all 5 callback_data values correct

All 11 command handler tests pass.

## Live Verification

Status: pending credentials
