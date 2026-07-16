# ADR-004: Telegram Bot Token Ownership

## Status
Accepted (updated Gate 2)

## Context
The mandate requires exactly one owner for the Telegram Bot Token. Running
two competing polling processes (Hermes Gateway + app bot) with the same token
causes conflicts: one process receives updates, the other doesn't, and
Telegram returns 409 Conflict.

## Decision
Use a dedicated Newsroom Telegram bot (`newsroom.delivery.bot`) as the sole
owner of the Bot API Token. Hermes Gateway may use a separate operator bot or
remain a terminal control plane.

## Gate 2 Update

### Sole Ownership Enforcement
- The `telegram-bot` Docker service is the only process that calls `getUpdates` (long-polling)
- `deleteWebhook` is called on startup to clear any competing webhook
- If a second process attempts to poll with the same token, Telegram returns 409 Conflict
- The bot's error classification handles the conflict case gracefully (returns data, logged)

### Bot Identity Verification
- On startup, the bot calls `getMe` to verify the token is valid
- Bot username logged with redacted token: `@username token=[REDACTED]`
- If identity query fails, bot enters degraded mode with `["identity_query_failed"]`

### Access Control
- Only explicitly configured numeric Telegram user IDs may invoke commands
- Fail-closed: empty allowlist denies everyone, no wildcard mode
- Checked on every command and every callback

### Delivery Separation
- The bot handles report delivery via `TelegramDelivery` (Bot API sendMessage)
- Scheduled delivery (via runner) also uses the same `TelegramDelivery` class
- Both paths use the same per-chunk state and cursor advancement logic
- Manual runs do not advance the scheduled delivery cursor

## Rationale
- The Newsroom bot needs polling for /report commands and inline callbacks
- Hermes Gateway already has its own token for the user's general AI assistant
- One token = one poller = no 409 conflicts
- The app bot is containerized and restartable independently

## Consequences
- Hermes cron delivers reports via the `--no-agent` script path (no polling)
- The app bot handles all interactive commands
- No shared token between Hermes Gateway and the Newsroom app
- Token never stored in Git, Docker images, database, logs, or reports
