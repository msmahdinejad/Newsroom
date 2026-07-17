# Gate 3 Cursors

**Status**: NOT YET EXECUTED (live)

## Cursor Implementation
- Per-channel durable cursor stored in telegram_channels.last_message_id
- Supplementary cursor in collection_cursors table (key: tg_default)
- Cursor advances only after persist_items succeeds
- Overlap safety window: re-fetches last 5 message IDs for edit detection
- Late-arriving messages accepted safely (idempotent by telegram_channel_id + telegram_message_id)

## Deterministic Verification
- Cursor advance after persist: PASS
- Cursor isolation between sources: PASS
- Cursor no advance on empty: PASS
- Cursor filter drops older: PASS
- Restart continues from cursor: PASS (integration)

## Blocked
Live cursor verification is blocked pending live collection.
