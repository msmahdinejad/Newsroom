# Final Production Runbook

This is the operator source of truth for the single-host production deployment.
Commands are shown from the repository root.

## Prerequisites

- Docker Desktop or Docker Engine with Compose v2
- Git
- `uv`
- PowerShell 7 on Windows, or an equivalent shell for direct Compose commands
- outbound HTTPS; a local proxy when required by the host network

Copy safe templates before the first start:

```powershell
Copy-Item .env.example .env
Copy-Item .env.providers.example .env.providers.local
```

Keep `.env.providers.local` and `.env.x.local` local and ignored. Complete the
Telegram and X values only on the production host. MTProto authorization is a
separate persistent session; never commit or copy the session into the image.

## Start, health, and stop

One-command production startup:

```powershell
.\scripts\up-production.ps1
```

One-command health check:

```powershell
.\scripts\health.ps1
```

One-command safe shutdown (named volumes remain):

```powershell
.\scripts\down.ps1
```

On Linux the direct equivalents are:

```bash
docker compose up -d --wait
docker compose ps
docker compose down
```

The migration service runs before workers. Do not start workers against an
older schema.

## Database migrations

Inspect and upgrade:

```powershell
uv run alembic current
uv run alembic heads
uv run alembic upgrade head
```

Production starts with `migrate`, so routine startup applies pending forward
migrations. Back up before upgrading between releases:

```powershell
.\scripts\backup.ps1
```

Restore is intentionally explicit and destructive to the current database:

```powershell
.\scripts\restore.ps1 -File newsroom-YYYYMMDD-HHMMSS.sql
```

## Source inventory

Supply the private workbook explicitly or through
`NEWSROOM_SOURCE_WORKBOOK`. The `All Sources` sheet is authoritative.

```powershell
uv run newsroom sources reconcile --workbook .\config\import\source-radar.xlsx
uv run newsroom sources status
```

Reconciliation is idempotent. Original workbook IDs and duplicate
classifications remain represented. Import updates metadata but does not delete
historical items or evidence.

Manual bounded collection:

```powershell
uv run newsroom collect
uv run newsroom collect --source-type rss
```

The production collector loop handles native HTTP platforms. Telegram MTProto
and X have dedicated owners. Failure of one source does not stop the rest.

When the network requires a proxy, set the appropriate ignored local setting:

- `COLLECTION_PROXY_URL` for native HTTP collectors;
- `TELEGRAM_PROXY_URL`, `TELEGRAM_PROXY_TYPE`, and
  `TELEGRAM_CONNECTION_MODE` for MTProto;
- `LLM_PROXY_URL` in `.env.providers.local` when an editorial endpoint
  requires an explicit supported proxy route.

Never include credentials in a diagnostic command or log excerpt.

## Telegram MTProto

Authorize once without deleting an existing session:

```powershell
docker compose run --rm telegram-authorize
```

The interactive login code and optional 2FA password are never stored in
`.env`. The `telegram_sessions` volume survives restart. The
`telegram-ingestor` service is the sole session owner.

Safe checks:

```powershell
docker compose ps telegram-ingestor
docker compose logs --tail 50 telegram-ingestor
```

Logs expose only safe transport and failure categories, never the proxy
endpoint, credentials, API hash, phone number, or session data.

## LLM providers

Configure and validate as described in `docs/LLM_PROVIDER_SETUP.md`:

```powershell
uv run python -m newsroom.editorial.router validate
docker compose up -d --build --force-recreate report-worker scheduler
```

Do not manually enable an unvalidated model. A provider with no access value is
`not configured`; a confirmed invalid value remains isolated until corrected.

## Processing and reports

Run processing stages:

```powershell
uv run newsroom process all
uv run newsroom report generate
```

Run the authoritative full pipeline:

```powershell
uv run newsroom pipeline run
```

Production scheduled reports run at Tehran 00:00, 06:00, 12:00, and 18:00.
The scheduled cursor advances only after a complete Telegram delivery. Failed
or partial delivery resumes missing chunks; no-news windows make no LLM calls.

## Telegram bot commands

The configured owner may use:

```text
/status
/latest
/report
/report new
/report comprehensive
/collect
/sources
/schedule
```

The bot is the sole Bot API polling owner. Commands are owner-restricted and
idempotent; persisted audit state uses one-way identity fingerprints.

## Routine operations

Check inventory and services:

```powershell
uv run newsroom sources status
.\scripts\health.ps1
docker compose ps
```

Validate configuration and code:

```powershell
docker compose config -q
uv run ruff check .
uv run mypy src
uv run pytest
```

Check public-release isolation:

```powershell
uv run python scripts\audit_release_exposure.py
```

The exposure check reports safe labels and locations only. A nonzero exit means
publication is blocked until tracked files, history, logs, and PostgreSQL are
clean.

## Restart recovery

Restart the complete stack:

```powershell
docker compose restart
.\scripts\health.ps1
```

After restart verify:

- scheduler jobs remain in the four Tehran windows;
- Telegram MTProto reconnects without reauthorization;
- source and platform cursors continue;
- provider cooldown/validation state reloads;
- accepted editorial artifacts and report lineage remain;
- delivery chunks and real Telegram message IDs remain;
- no job is stuck or duplicated.

## Incident handling

1. Run the health script and inspect the affected service only.
2. Use safe failure categories and timestamps; do not paste local values.
3. Keep source failures isolated and preserve evidence/cursors.
4. For provider authentication rejection, correct only the affected value and
   rerun bounded validation.
5. For Telegram network failures, verify the selected route without deleting
   or recreating the session.
6. For a partial delivery, rerun the same pipeline window; do not delete the
   delivery or cursor.
7. Back up PostgreSQL before manual recovery or release migration.

## Known capacity boundaries

This release is a bounded single-host system. Provider quotas, source rate
limits, inaccessible/private channels, and host network policy are external
limits. Access-value rotation is resilience, not multiplied quota. Collected
third-party content retains its original rights and is not redistributed as
project-licensed source code.
