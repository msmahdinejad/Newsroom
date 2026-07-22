# Gate 6 — Access & Safety Verification

## Never printed or persisted (protected local values)

The following are **never** committed, printed in logs, or included in
documentation/Telegram responses:

- `.env` (gitignored)
- `.env.providers.local` (locally excluded; canonical provider runtime source)
- `.env.x.local` (gitignored)
- Telegram session files (`data/sessions/`, `*.session*` — gitignored)
- Agent-Reach local configuration (`data/agent-reach/` — gitignored)
- browser session material
- local Qwen configuration (`.qwen/` — untouched)
- local Specify configuration (`.specify/` — untouched)

Provider/model health, queue usage, circuit state, route attempts, and key-pool
state contain only safe metadata. Provider keys are represented by one-way
fingerprints; original values are absent from PostgreSQL, health output, logs,
tracked files, and documentation.

## Log redaction

`newsroom/logging.py` adds a `RedactingFilter` that scrubs from every log
record:

- Telegram bot tokens (`bot<digits>:<token>` → `***`)
- `api_key=`/`token=`/`password=`/`secret=`/`auth=` assignments → `***`
- `Bearer <token>` → `***`

`httpx`, `telethon`, and `httpcore` loggers are set to `WARNING` so request
URLs (which embed the bot token) are not emitted at INFO. Verified: the live
delivery log lines no longer contain the bot token.

## Telegram command responses (no protected data)

`/status`, `/sources`, `/schedule`, `/collect`, `/latest`, `/report*`
return only aggregate counts, states, and timestamps — never tokens,
session-file contents, personal identifiers, or protected configuration.
Verified by deterministic tests `test_status_text_has_no_secrets` and the
bot command dispatch tests.

## Treated content as data only

All collected content is stored as JSONB in `raw_items.raw_data` and
normalized into standard fields. It never alters application configuration
and never creates executable instructions. Collector adapters return plain
dicts; the pipeline persists them without eval/exec.

## SSRF & bounded reading

- Native HTML reader and Agent-Reach web adapters enforce SSRF protection:
  http(s) only, reject private/loopback/link-local IPs, DNS validation,
  reject redirect-based SSRF, bounded response size (`COLLECTION_MAX_SIZE_MB`),
  bounded timeouts, no JS/forms/login.
- YouTube handle resolution uses a crawler UA only for the public
  channel-metadata read (read-only; no auth, no cookies persisted).
- Reddit uses the public `.rss` feed (browser UA, no login).
- Agent-Reach subprocesses run in an isolated worker (no app secrets, bounded
  CPU/memory, isolated config dir); only the controlled runner may launch
  them; source content and editorial AI cannot produce commands.

## Non-public / membership communities

For access-dependent communities (Discord/Slack/Bot): only documented public
endpoints or already-configured owner access are used; no alternate access
is attempted. Such sources stay registered with `operational_state=inactive`
and `inactive_reason=access_required` (9 sources). Their historical items
are preserved.

## `.qwen/` and local `.specify/` untouched

Confirmed unchanged across every commit (`git status` shows no modifications
to `.qwen/` or `.specify/`). Test placeholders are synthetic and limited to
tests.
