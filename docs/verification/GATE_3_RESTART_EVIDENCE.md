# Gate 3 Restart Evidence

**Status**: NOT YET EXECUTED (live)

## Restart Continuation
- Cursor (last_message_id) persisted in telegram_channels table
- New collector instance reads cursor from DB
- Collection continues from last_message_id with overlap window

## Deterministic Verification
- Restart continues from cursor (integration): PASS

## Blocked
Live restart verification is blocked pending live collection.
