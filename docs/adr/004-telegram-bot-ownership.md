# ADR-004: Telegram Bot Token Ownership

## Status
Accepted

## Context
The mandate requires exactly one owner for the Telegram Bot Token. Running
two competing polling processes (Hermes Gateway + app bot) with the same token
causes conflicts: one process receives updates, the other doesn't, and
Telegram returns 409 Conflict.

## Decision
Use a dedicated Newsroom Telegram bot (`newsroom.delivery.bot`) as the sole
owner of the Bot Token. Hermes Gateway may use a separate operator bot or
remain a terminal control plane.

## Rationale
- The Newsroom bot needs polling for /report commands and inline callbacks
- Hermes Gateway already has its own token for the user's general AI assistant
- One token = one poller = no 409 conflicts
- The app bot is containerized and restartable independently

## Consequences
- Hermes cron delivers reports via the `--no-agent` script path (no polling)
- The app bot handles all interactive commands
- No shared token between Hermes Gateway and the Newsroom app
