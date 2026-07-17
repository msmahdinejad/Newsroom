# Gate 3 Pipeline Delivery

**Status**: NOT YET EXECUTED (live)

## Pipeline Flow
Telegram message → raw item → normalization → exact dedup → near dedup → story clustering → evidence packet → Persian report → output bot delivery

## Integration Points
- collect.py: telegram source type handled with dedicated persist_items
- normalize.py: _normalize_telegram extracts text, outbound links, permalink
- cursors.py: filter_new_items and advance_cursor_from_items support telegram
- Pipeline runner: no changes needed — uses existing deterministic pipeline

## Blocked
Live pipeline delivery is blocked pending live collection.
