# Gate 3 Edits and Forwards

**Status**: NOT YET EXECUTED (live)

## Edit Handling
- Same (channel_id, message_id) updates existing RawItem in place
- Text, caption, links, entities, hashes, edit_ts updated
- Content hash change detects edited vs identical
- Repeated identical edits: skipped (same content_hash)

## Forward Attribution
- Preserves: forward_from_channel_id, forward_from_channel_name, forward_from_message_id, forward_from_date, forward_timestamp
- Does not infer hidden origin information
- Does not expose private account details

## Deterministic Verification
- Edited message updates in place: PASS
- Edit updates existing item (integration): PASS
- Forward attribution persisted (integration): PASS

## Blocked
Live edit/forward observation is blocked pending live collection.
