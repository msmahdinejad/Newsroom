# Gate 2 — Security Verification

## Secret Storage Audit

### Bot Token
- **Git**: Token never committed. `.env` in `.gitignore`. Secret scan: 0 matches.
- **Docker images**: `.dockerignore` excludes `.env`. Token passed via environment variable.
- **Database tables**: No token field in any model. Verified: `test_no_token_in_models`.
- **Logs**: Token never logged. `redact_token()` returns only `[REDACTED]`.
- **Command evidence**: Bot responses contain report IDs, never tokens.
- **Reports**: Report content is editorial text, no tokens.
- **Shell history**: Token entered via `.env` file, not shell arguments.

### Chat ID
- Stored as SHA-256 hash (first 16 chars) in `deliveries.chat_id`
- Raw chat ID never persisted in database
- `chat_ref` field stores `chat_{hash[:8]}` for safe labeling

### Authorized User IDs
- Stored in environment variable `TELEGRAM_AUTHORIZED_USER_IDS`
- Parsed to `set[int]` at runtime
- Never persisted in database tables

## Redaction

### Token Redaction (client.py)
```python
def redact_token(_token: str | None = None) -> str:
    return "[REDACTED]"
```
- Verified: `test_redact_token_no_fragment` — no prefix, suffix, or ellipsis fragments
- Used in bot startup log: `token=[REDACTED]`

### Denial Message
- `deny_message()` returns: `⛔ دسترسی غیرمجاز.`
- No infrastructure details: no "token", "database", "api", "config", "password"
- Verified: `test_deny_message_no_infrastructure_details`

## Access Control Security

- Fail-closed: empty allowlist = deny all
- No wildcard mode
- Malformed entries skipped (not treated as wildcards)
- Checked on every update (message and callback)
- Unauthorized users get generic denial, no operational details

## URL Safety

- `format_link()` in render.py validates URL scheme
- Rejects `javascript:` and `data:` URLs
- Only allows `http://`, `https://`, and `t.me/` links
- All link text is HTML-escaped

## HTML Safety

- Parse mode: HTML (documented and tested)
- All user/source-controlled text escaped via `html.escape()`
- Persian text preserved (no HTML-special characters)
- No `eval()` on any data (Gate 0 audit resolved in Gate 1)

## Test Evidence

### Security tests (8 tests, all pass)
- `test_no_hardcoded_token_in_source` — regex scan of all source files
- `test_redact_token_no_fragment` — complete value only `[REDACTED]`
- `test_env_example_has_empty_token` — `TELEGRAM_BOT_TOKEN=` (empty)
- `test_env_example_has_empty_authorized_user_ids` — `TELEGRAM_AUTHORIZED_USER_IDS=` (empty)
- `test_env_in_gitignore` — `.env` and `.env.local` in `.gitignore`
- `test_no_token_in_models` — no "token" column in any model
- `test_deny_message_no_secrets` — no secrets in denial message
- `test_chat_id_hashed_not_stored_raw` — chat_id stored as hash

### Git Secret Scan
- `git diff` scanned for token pattern `\d{6,}:[A-Za-z0-9_-]{30,}`
- Result: 0 matches in all changed files
- No `.env` files tracked in git

## Docker Security

- Token passed as environment variable: `TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:-}`
- `.dockerignore` excludes `.env`
- Container runs as non-root user `newsroom`
- No secrets baked into image layers

## Credential Contract

Required secret names (minimal and clear):
- `TELEGRAM_BOT_ENABLED` — feature flag (bool)
- `TELEGRAM_BOT_TOKEN` — Bot API token (string)
- `TELEGRAM_AUTHORIZED_USER_IDS` — comma-separated numeric IDs
- `TELEGRAM_CHAT_ID` — default delivery chat (optional, inferred from incoming message)

Not requested in Gate 2:
- `TELEGRAM_API_ID` — Gate 3 (MTProto ingestion)
- `TELEGRAM_API_HASH` — Gate 3
- `TELEGRAM_PHONE` — Gate 3

## Live Verification

Status: pending credentials
