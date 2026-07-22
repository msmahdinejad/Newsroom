# Gate 2 — Live Telegram Evidence

## Date: 2026-07-16

The output bot passed `getMe`, webhook cleanup, and conflict-free polling.
Bot tokens, authorized user identifiers, and destination chat identifiers are
redacted from this tracked evidence file.

## Commands and authorization

Authorized `/start` and `/help` commands succeeded. A synthetic unauthorized
identity was denied without exposing infrastructure details. `/latest`,
`/report`, `/report new`, `/report comprehensive`, and the Persian inline
button callback completed through the canonical command path.

## Idempotency and locking

- Replayed updates and callbacks were skipped.
- The manual-new request created one report, one command request, and one
  delivery.
- Eight recorded update IDs were distinct.
- A report request returned `busy` while the PostgreSQL pipeline lock was held
  and succeeded after release.

## Multi-chunk and partial recovery

Report 75 delivered five ordered chunks with message IDs 23–27. Delivery 70
failed after three of five chunks, resumed the same row, preserved message IDs
28–30, and completed with message IDs 31–32. Failed and partial deliveries did
not advance the scheduled cursor.

## Cursor and restart behavior

Complete delivery advanced the cursor to report 79; confirming it twice did not
advance twice, and manual reports never moved the scheduled cursor. After the
bot was killed and restarted, polling resumed without a 409 conflict, a replayed
update was skipped, `/latest` succeeded, and all delivery state remained
durable.

## Security

The live token was absent from Git history, tracked files, PostgreSQL, logs,
and evidence output. Synthetic credential-like fixtures remain limited to
tests. `.env` is excluded from both Git and Docker build context.
