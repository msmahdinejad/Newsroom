# ADR-005: Telegram Identity Separation

## Status
Accepted (Gate 3)

## Context
Gate 2 established a verified Bot API output bot (`@newsroom_bot`) that:
- Sends Persian reports to authorized users
- Receives `/report`, `/latest`, callback commands
- Owns the Bot Token
- Is the sole polling owner via `getUpdates`

Gate 3 adds MTProto ingestion — reading public Telegram channels using a
**user account** (not a bot). This creates two distinct Telegram identities.

The mandate requires strict separation:
- The output bot must not collect source channels
- The ingestor must not send reports, reply, react, or manipulate
- No identity reuse, no token reuse, no session reuse

## Decision

### Output Identity (Gate 2, unchanged)
- **Identity type**: Bot API bot
- **Credential**: `TELEGRAM_BOT_TOKEN` (in `.env`, untracked)
- **Container**: `telegram-bot` Docker service
- **Operations**: `sendMessage`, `getUpdates`, `answerCallbackQuery`, `deleteWebhook`
- **Cannot**: access MTProto, read channels, collect messages

### Ingestion Identity (Gate 3, new)
- **Identity type**: User account (MTProto)
- **Credentials**: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE` (in `.env`, untracked)
- **Session**: `TELEGRAM_SESSION_PATH` — separate encrypted session file in restricted Docker volume
- **Container**: `telegram-ingestor` Docker service (separate from `telegram-bot`)
- **Operations**: `iter_messages` (read-only), `get_entity` (resolve), `get_me` (verify identity)
- **Cannot**: send messages, post, react, vote, invite, manipulate views, access Bot Token

### Enforcement
- The `telegram-bot` container has no `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`/`TELEGRAM_PHONE` env vars
- The `telegram-ingestor` container has no `TELEGRAM_BOT_TOKEN` env var
- The session file is in a dedicated Docker volume (`telegram_sessions`) not shared with the bot
- The collector code (`TelegramMTProtoCollector`) has no `send_message` capability
- The delivery code (`TelegramDelivery`) has no MTProto client

## Rationale
- Bot API and MTProto are fundamentally different protocols with different capabilities
- A bot cannot read channel messages unless it is an admin; a user account can read public channels
- Identity separation prevents accidental cross-contamination of read/write capabilities
- If the ingestor session is compromised, the attacker cannot send messages through the output bot
- If the output bot token is compromised, the attacker cannot access the MTProto session

## Consequences
- Two separate authorization flows (bot token setup vs MTProto one-time login)
- Two separate Docker services with different env vars
- Two separate credential sets in `.env`
- The MTProto session requires one-time interactive authorization (`authorize-telegram` command)
- The output bot remains operational even if the ingestor is disabled
