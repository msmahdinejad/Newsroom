# Gate 1 — Collection Cursor Evidence

## Implementation

**Module**: `src/newsroom/pipeline/cursors.py`
**Table**: `collection_cursors` (per source, per cursor_key)

### RSS cursor structure

```json
{
  "last_published": "2026-07-14T11:00:00+00:00",
  "seen_entry_ids": ["id1", "id2", ...],
  "updated_at": "2026-07-16T..."
}
```

### GitHub cursor structure

```json
{
  "last_release_id": "12345",
  "updated_at": "2026-07-16T..."
}
```

## Behavior verified

### First collection
- Empty cursor → all items returned by `filter_new_items`
- Cursor saved after successful persistence

### Second incremental collection
- Items older than `last_published` dropped
- Items already in `seen_entry_ids` dropped
- New items pass filter

### Restart and continuation
- Cursor loaded from DB on next collection cycle
- Resumes from persisted cursor position

### Failed persistence
- Cursor NOT advanced if no items persisted (`advance_cursor_from_items` with empty list returns unchanged cursor)

### Failed source fetch
- Exception caught, cursor NOT advanced, source health degraded

### Duplicate from overlap
- Overlapping items (equal published/release_id) kept for safety
- `content_hash` dedup makes them idempotent at `RawItem` level

### Late-arriving item
- Equal published timestamp allowed through filter
- Deduped by content_hash if already present

### Source with no new items
- Filter returns empty list
- Cursor unchanged

## Tests

### Unit (6 tests)
- `test_first_collection_empty_cursor_returns_all`
- `test_rss_drops_older_items_keeps_overlap`
- `test_github_drops_lower_release_ids`
- `test_advance_rss_uses_max_published`
- `test_advance_github_uses_max_release_id`
- `test_advance_no_items_keeps_cursor`

### Integration (3 tests)
- `test_first_and_incremental_cursor` — real DB roundtrip
- `test_cursor_not_advanced_on_empty_persist`
- `test_github_cursor_roundtrip`

All 9 cursor tests passed.

## DB evidence

```
SELECT count(*) FROM collection_cursors → 36
```

36 cursors active across 39 sources (3 test sources excluded).
