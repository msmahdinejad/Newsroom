# Persian AI Newsroom

A production-oriented, local-first newsroom that collects global AI and
developer news, preserves evidence and source history, creates grounded Persian
reports, and delivers them to Telegram.

## معرفی فارسی

«اتاق خبر فارسی هوش مصنوعی» خبرهای حوزهٔ هوش مصنوعی، برنامه‌نویسی، ابزارهای
توسعه و متن‌باز را از منابع عمومی گردآوری می‌کند. سامانه هویت منبع، نشانگر
ادامهٔ دریافت، شواهد و سابقهٔ سلامت را نگه می‌دارد؛ خبرهای تکراری را ادغام
می‌کند؛ و گزارش فارسی مستند می‌سازد. در صورت اختلال یک منبع یا ارائه‌دهندهٔ
مدل، سایر مسیرها به کار ادامه می‌دهند.

## Overview

The application runs as a set of bounded Python workers backed by PostgreSQL.
Collectors ingest source items incrementally. A deterministic processing
pipeline normalizes, deduplicates, clusters, ranks, and packages evidence.
A persistent multi-provider LLM router can perform hierarchical map/reduce
editing, with a deterministic editorial implementation as the terminal
fallback. APScheduler creates reports at 00:00, 06:00, 12:00, and 18:00 in
`Asia/Tehran`; delivery state prevents duplicate Telegram messages.

### Key features

- Stable source, item, cursor, story, evidence, report, and delivery identities
- Source-specific retries, cooldowns, failure isolation, and durable health
- Native bounded collectors plus an audited, revision-pinned Agent-Reach layer
- Hierarchical Persian editorial generation for large evidence sets
- Gemini, Mistral, Groq, and NVIDIA routes with key pools, quotas, model
  fallback, provider circuit breakers, and safe persisted attempt metadata
- Deterministic operation when no editorial provider is available
- Idempotent scheduled and manual Telegram delivery
- Docker Compose production stack with persistent volumes and health checks

### Supported source platforms

| Platform | Production path |
| --- | --- |
| RSS and Atom | Native feed collector |
| Websites and public newsletter pages | Bounded native HTML reader |
| GitHub repositories/releases | Native GitHub collector |
| YouTube channels | Native YouTube RSS collector |
| Reddit communities | Native public RSS collector |
| Telegram channels | Telethon MTProto user session |
| X account timelines | Isolated Agent-Reach worker using local X access state |
| Other public communities | Bounded web or audited Agent-Reach capability when supported |

Some platforms require owner-supplied credentials, a reachable network route,
or acceptance of the upstream platform's terms. Unsupported or inaccessible
inventory rows remain accounted for but inactive with an explicit reason.

## Architecture

```text
Source inventory
      |
      v
bounded collectors --> raw items + cursors + source health
      |
      v
normalize --> deduplicate --> cluster --> rank --> evidence packets
                                                   |
                                                   v
                                    queued multi-provider router
                                    (deterministic fallback)
                                                   |
                                                   v
                                Persian report --> Telegram delivery
```

PostgreSQL is the durable coordination boundary. Separate workers own native
collection, X/Agent-Reach, Telegram MTProto ingestion, scheduling/editorial
work, and Telegram Bot API delivery. See
[the final architecture](docs/FINAL_ARCHITECTURE.md) and the
[architecture records](docs/adr/).

## Prerequisites

- Git
- Docker Engine with Docker Compose v2 (Docker Desktop is supported)
- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)
- PowerShell 7 on Windows for the repository helper scripts

Linux and macOS users can run the equivalent `uv` and `docker compose`
commands shown below. Live Telegram, X, and editorial integrations are
optional for deterministic development and CI.

## Quick start

### Windows PowerShell

```powershell
git clone <repository-url>
Set-Location newsroom
Copy-Item .env.example .env
Copy-Item .env.providers.example .env.providers.local
uv sync --frozen --extra dev --extra telegram
docker compose up -d postgres
uv run alembic upgrade head
uv run pytest tests -m "not integration"
```

### Linux or macOS

```bash
git clone <repository-url>
cd newsroom
cp .env.example .env
cp .env.providers.example .env.providers.local
uv sync --frozen --extra dev --extra telegram
docker compose up -d postgres
uv run alembic upgrade head
uv run pytest tests -m "not integration"
```

The example configuration disables integrations that require private access.
Use a strong `POSTGRES_PASSWORD` before production deployment. The Compose
database is bound to loopback by default.

## Configuration

- `.env` contains application and service settings. It is ignored by Git.
- `.env.providers.local` is the **only** runtime source for editorial provider
  access values. It is ignored by Git and mounted only into services that need
  router configuration.
- `.env.x.local` contains local X access state. It is ignored by Git and is
  mounted only into the isolated Agent-Reach worker.
- The Telethon session is stored in the `telegram_sessions` Docker volume, not
  in the repository.

Copy the supplied examples and fill only the integrations you intend to use.
Never commit local environment files, proxy credentials, cookies, access
tokens, or Telethon session files. Provider-specific setup is documented in
[LLM provider setup](docs/LLM_PROVIDER_SETUP.md).

## LLM routing and fallback

Editorial map and reduction calls enter one bounded queue. The router tries a
healthy key for the preferred validated model, then another key, another
validated model on the same provider, and the next provider after a circuit
breaker opens. The final route is deterministic editorial generation.

Default provider preference is Gemini, Mistral, Groq, then NVIDIA. Models are
not production-enabled merely because they appear in configuration: a bounded
live validation must prove Persian output, structured schema compatibility,
grounding-compatible parsing, and output limits. Health and attempt records
contain safe labels and fingerprints, never provider access values.

## Telegram setup

Telegram ingestion and Telegram delivery use separate identities.

### Output bot

1. Create a bot with BotFather.
2. Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and the numeric
   `TELEGRAM_AUTHORIZED_USER_IDS` in `.env`.
3. Set `TELEGRAM_BOT_ENABLED=true`.

The owner-restricted bot supports `/status`, `/latest`, `/report`,
`/report new`, `/report comprehensive`, `/collect`, `/sources`, and
`/schedule`.

### MTProto ingestion

1. Obtain `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` for a dedicated account.
2. Set them with `TELEGRAM_PHONE` in `.env`.
3. Configure a network route if direct MTProto is unavailable. Supported
   modes are `direct`, `abridged`, `intermediate`, `full`, `obfuscated`, and
   explicitly configured `mtproxy`; regular proxies may be SOCKS5 or HTTP.
4. Authorize once:

   ```powershell
   docker compose --profile authorize run --rm telegram-authorize
   ```

5. Set `TELEGRAM_INGESTOR_ENABLED=true` and start the ingestor.

Do not delete or share the session volume. Login codes and two-factor
passwords are entered interactively and are never stored in `.env`.

## Source inventory

The full production workbook is private source data and is intentionally
excluded from Git and Docker build contexts. Supply a workbook locally as
`config/import/source-radar.xlsx`, using the schema described in
[source inventory documentation](docs/SOURCE_INVENTORY.md), then run:

```powershell
uv run newsroom sources reconcile
uv run newsroom sources status
```

Import is idempotent. Original workbook row IDs and inactive rows remain
represented; disabling a source does not delete collected evidence.

## Local development

```powershell
uv sync --frozen --extra dev --extra telegram
docker compose up -d postgres
uv run alembic upgrade head
uv run ruff check src tests
uv run mypy src/newsroom
uv run pytest tests -m "not integration"
uv run pytest tests/integration
docker compose config --quiet
```

PostgreSQL integration tests default to the loopback Compose database on port
`55432`; set `DATABASE_URL` to use an isolated test database. Live integration
checks are deliberately opt-in and are not part of public CI.

## Production deployment

1. Copy both environment examples to their ignored local counterparts.
2. Set a strong database password and only the integrations you need.
3. Supply the private source inventory and reconcile it.
4. Start the complete stack:

   ```powershell
   .\scripts\up-production.ps1
   ```

   Or on a POSIX host:

   ```bash
   docker compose up -d --wait
   ```

5. Confirm service and application health:

   ```powershell
   docker compose ps
   uv run newsroom health
   ```

Migrations run through the one-shot `migrate` service before dependent workers
start. Named volumes retain PostgreSQL data, Agent-Reach state, and the
Telethon session across restarts. See the
[final production runbook](docs/FINAL_PRODUCTION_RUNBOOK.md) before enabling
live access.

## Operating commands

```powershell
uv run newsroom health                     # safe application health
uv run newsroom sources status             # inventory reconciliation
uv run newsroom collect                    # bounded collection pass
uv run newsroom collect --source-type rss  # one source type
uv run newsroom pipeline run               # process, report, and deliver
docker compose logs --tail 200              # recent service logs
docker compose restart                      # restart, preserving volumes
docker compose down                         # stop, preserving volumes
```

The production schedule is `00,06,12,18` in `Asia/Tehran`. A failed generation
or partial delivery does not advance the scheduled delivery boundary.

## Database migrations

```powershell
docker compose up -d postgres
uv run alembic upgrade head
uv run alembic current
```

Back up production data before an upgrade. Never run test cleanup commands
against a production database.

## Testing

```powershell
# Fast deterministic suite; no live access required
uv run pytest tests -m "not integration"

# Real PostgreSQL suite
uv run pytest tests/integration

# Full local regression suite
uv run pytest tests

# Quality and packaging checks
uv run ruff check src tests
uv run mypy src/newsroom
docker compose config --quiet
docker build --tag newsroom:local .
```

Tests that use real provider, Telegram, X, or other upstream access must remain
explicitly opt-in and must load only ignored local configuration.

## Known limitations

- The production source workbook and collected third-party content are not
  redistributed with the project.
- Telegram MTProto may require a host proxy in networks that block Telegram.
- X and some community platforms require local owner access and remain disabled
  without it.
- Upstream sites can change markup, rate limits, or access policies.
- LLM availability and quota are provider/account dependent; deterministic
  editorial remains available but is not equivalent to AI generation.
- The project is designed for a single trusted operator, not as a public
  multi-tenant service.

## Contributing and support

Read [CONTRIBUTING.md](CONTRIBUTING.md), the
[Code of Conduct](CODE_OF_CONDUCT.md), and [SUPPORT.md](SUPPORT.md) before
opening a contribution. Report security issues using the private process in
[SECURITY.md](SECURITY.md), not a public issue.

## License and content rights

Project code and original documentation are licensed under the
[MIT License](LICENSE). Dependencies retain their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The license does **not** relicense collected articles, posts, media, the private
source inventory, provider output, platform data, or any other third-party
content. Operators are responsible for complying with upstream terms,
copyright, privacy, and applicable law.
