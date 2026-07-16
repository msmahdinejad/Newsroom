# Gate 2 — Pre-live Consistency Check

## Date

2026-07-16 (pre-credential)

## Canonical environment variables

| Variable | Role |
|---|---|
| `TELEGRAM_BOT_ENABLED` | feature flag; false = idle healthy disabled mode |
| `TELEGRAM_BOT_TOKEN` | Bot API token (secret; .env only) |
| `TELEGRAM_AUTHORIZED_USER_IDS` | comma-separated numeric Telegram user IDs |
| `TELEGRAM_CHAT_ID` | optional default delivery chat |
| `TELEGRAM_TEST_CHAT_ID` | optional test chat override |

**Renamed:** `TELEGRAM_AUTHORIZED_USERS` → `TELEGRAM_AUTHORIZED_USER_IDS` (no alias; fail-closed if empty/malformed).

## Token redaction

`redact_token()` returns only `[REDACTED]`. No prefix/suffix fragments in logs, health, or evidence.

## User-ID discovery

Local one-shot: `uv run python scripts/discover_telegram_ids.py`

- Reads token from .env
- Prints user_id, chat_id, optional username
- No Token display, no DB writes, no reports, no cursor advance
- Not a production bot command; stop telegram-bot first if it is polling

## Token ownership

| Service | Has token env? | Polls getUpdates? |
|---|---|---|
| `telegram-bot` | yes | **yes — sole poller** |
| `scheduler` | yes (send only) | no |
| `collector` / `report-worker` / `migrate` / `telegram-ingestor` | no Bot Token | no |
| Hermes Gateway | separate operator bot (not this compose service) | must not share this Token |

Runtime command of sole poller: `uv run python -m newsroom.delivery.bot`

## Pre-live commands (executed)

| Check | Result |
|---|---|
| `uv run pytest tests/` | 218 passed |
| Ruff `src/ tests/ scripts/discover_telegram_ids.py` | clean |
| MyPy `src/` | clean |
| Secret scan (token pattern on diff) | only synthetic fixtures in unit tests; no real secrets |
| Fragment pattern `1234...` in docs/src | removed |
| `docker compose config` | exit 0; sole poller `newsroom.delivery.bot` |
| Canonical allowlist env | `TELEGRAM_AUTHORIZED_USER_IDS` only |
| `redact_token()` | `[REDACTED]` only |

## Status

Phase A complete. Ready for Phase B credential placement (no values printed).
