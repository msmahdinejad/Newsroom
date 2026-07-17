# ADR-006: MTProto Session Storage

## Status
Accepted (Gate 3)

## Context
The MTProto session file is a sensitive credential — it contains the auth key
that proves the ingestor identity. If leaked, an attacker can impersonate the
user account. Unlike the Bot Token (which can be revoked/regenerated from the
bot father), the MTProto session represents a user login.

Requirements from the Gate 3 mandate:
- Never commit the session to Git
- Never copy it into a Docker image
- Never include it in normal backups
- Never expose its bytes or auth key
- Never print its path in user-facing bot messages
- Persist in a dedicated Docker volume or restricted local path
- Run the ingestor as a non-root user
- Restrict filesystem permissions where supported
- Detect missing, invalid, expired, and corrupted sessions
- Provide a documented safe reauthorization procedure
- Prevent the output-bot container from accessing the MTProto session

## Decision

### Local development
- Session path: `TELEGRAM_SESSION_PATH` (default: `./data/sessions/newsroom_ingestor.session`)
- The directory `data/sessions/` is excluded from:
  - `.gitignore` (never committed)
  - `.dockerignore` (never baked into images)
- File permissions restricted to `0o700` where supported (Unix)
- Windows: path-based isolation only (no Unix permissions)

### Docker
- Session stored in dedicated named volume: `telegram_sessions`
- Mounted at `/data/sessions` inside the `telegram-ingestor` container
- NOT shared with `telegram-bot` container
- The `telegram-bot` service has no `volumes:` entry for `telegram_sessions`
- Dockerfile creates `/data/sessions` and chowns to `newsroom` user
- Container runs as non-root user `newsroom`

### Detection
- `_ensure_client()` checks `is_user_authorized()` after connect
- Missing session → `CollectionError(recoverable=False)` with clear message
- Invalid/expired session → same error path, triggers reauthorization flow
- Corrupted session → Telethon raises, caught and classified as `auth_error`

### Safe Reauthorization
1. Stop the ingestor service: `docker compose stop telegram-ingestor`
2. Remove the old session: `docker volume rm newsroom_telegram_sessions` (or delete local file)
3. Run: `python -m newsroom.sources.authorize_telegram`
4. Enter login code interactively (getpass — never echoed)
5. Enter 2FA password interactively if required (getpass — never echoed)
6. Restart: `docker compose up -d telegram-ingestor`

### Logging
- Session path is never logged in full — shown as `[PROTECTED]` in health checks
- No session bytes, auth keys, or session content ever appear in logs
- Authorization result file records only: success/failure, redacted self ID, session_configured

## Rationale
- The session file is the equivalent of a stored password — treat it as such
- Docker named volumes provide isolation without baking secrets into images
- The `authorize-telegram` command uses `getpass` to ensure login codes and passwords are never echoed
- Lock file prevents concurrent authorization (which could corrupt the session)
- The `newsroom` non-root user cannot read other services' volumes

## Consequences
- One-time interactive authorization required before first collection
- Session survives container restarts (persistent volume)
- If the volume is lost, reauthorization is required
- The `telegram-bot` service cannot access MTProto session even if compromised
