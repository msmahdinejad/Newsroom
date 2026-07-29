# Newsroom

Newsroom is a self-hosted, local-first news collection and reporting system for
operator-defined subjects. It collects public sources incrementally, keeps
durable cursors and evidence lineage in PostgreSQL, produces grounded reports
through a bounded multi-provider LLM router, and delivers them through Telegram.

The public repository contains application code, migrations, tests,
credential-free examples, and an optional starter source catalog. It contains
no production database, collected content, operator identity, API key, cookie,
proxy credential, Telegram session, or private source inventory.

## Features

- Websites/feeds, GitHub, Reddit, Telegram, and X collectors
- Source-level cursors, health, validation, cooldowns, and failure isolation
- Named digests with independent topics, terms, sources, language, timezone,
  story budget, Telegram minimum, and schedule
- Report and bot localization for `en` and `fa`
- Protocol adapters for OpenAI-compatible, Gemini-native, and Anthropic-native
  providers, including operator-defined provider names and model IDs
- Bounded queues, quotas, key pools, model fallback, and circuit breakers
- Bounded model-catalog discovery; every route remains disabled until validation
- Grounded Gemini Search and Deep Research source suggestions with explicit
  approval before activation
- Grounded structured output with evidence and provider lineage
- Idempotent report generation and chunked Telegram delivery
- Runtime source management from the CLI or owner-restricted Telegram bot
- Digest-local schedules and IANA timezones stored in PostgreSQL
- Docker Compose deployment with unprivileged application containers

## Requirements

- Git
- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- Docker Engine with Docker Compose v2

PowerShell, Bash, and other shells can all run the same Python bootstrap.

## Quick start

Clone the repository and choose one source mode:

```bash
git clone <repository-url> newsroom
cd newsroom

# Use the safe starter catalog.
python scripts/bootstrap.py --source-mode default

# Or start with no sources.
python scripts/bootstrap.py --source-mode empty

# Or import your own CSV/XLSX source file.
python scripts/bootstrap.py --source-mode custom --source-file ./my-sources.csv
```

Add `--start` to build and start the complete stack:

```bash
python scripts/bootstrap.py --source-mode default --start
```

The bootstrap is idempotent. It creates missing ignored local configuration,
generates a random PostgreSQL password, preserves existing local files, installs
dependencies, starts PostgreSQL, applies migrations, and initializes the chosen
source registry.

## Source choices

The repository supports three first-run modes:

| Mode | Result |
| --- | --- |
| `empty` | No sources. Add everything yourself. |
| `default` | Imports the credential-free default subset. |
| `custom` | Imports an operator-supplied CSV or XLSX file. |

List every starter key:

```bash
uv run newsroom sources catalog
```

Choose only specific starter entries:

```bash
python scripts/bootstrap.py \
  --source-mode default \
  --select python-insider,github-blog,telegram-coding-news
```

Sources that require authentication or an additional network route are not
enabled by the default subset. They can be selected explicitly after their
integration is configured.

Manage the registry later without editing the database:

```bash
uv run newsroom sources list
uv run newsroom sources add \
  --name "Example feed" --type rss --url https://example.org/feed.xml
uv run newsroom sources import --file ./additional-sources.csv
uv run newsroom sources enable 42
uv run newsroom sources disable 42
uv run newsroom sources delete 42 --confirm
```

Deletion is an audit-preserving archive: collected items, cursors, and report
lineage remain intact. See [source management](docs/sources.md).

## Digests and subjects

The source adapters are intentionally fixed to Telegram, X, Reddit, GitHub,
and websites. The subject is not fixed: each named digest owns an arbitrary
operator-defined interest policy and an independent delivery schedule.

```bash
uv run newsroom digests create climate \
  --name "Climate policy" \
  --topic "Climate policy, renewable energy markets, and grid storage" \
  --language en \
  --timezone Europe/Berlin

uv run newsroom digests update climate \
  --include solar,storage \
  --exclude celebrity \
  --sources telegram,web,reddit \
  --count 20 \
  --telegram-min 4 \
  --schedule 08:00,17:30

uv run newsroom report generate --digest climate
```

The migrated `default` digest preserves the programming-focused preset for
existing installations. New digests are not programming-specific.

## Local configuration

Bootstrap creates three ignored files:

| File | Purpose |
| --- | --- |
| `.env` | Application, database, Telegram, scheduler, and collector settings |
| `.env.providers.local` | LLM access values, models, quotas, and provider routes |
| `.env.x.local` | X cookies for the isolated social collector |

Their tracked counterparts contain blank values and safe defaults:

- `.env.example`
- `.env.providers.example`
- `.env.x.example`

Never pass credentials as command-line arguments. Never put provider access
values in `.env`; the router reads them only from `.env.providers.local`.

See [configuration](docs/configuration.md) for Telegram authorization,
provider models, X cookies, proxies, and production hardening.

## LLM providers and models

Enable only providers you configure locally:

```dotenv
# .env
EDITORIAL_ENABLED=true

# .env.providers.local
LLM_ROUTER_ENABLED=true
GEMINI_API_KEYS=
MISTRAL_API_KEYS=
GROQ_API_KEYS=
NVIDIA_API_KEYS=
```

`LLM_PROVIDER_ORDER` may contain additional provider names. For each name,
configure its key pool, exact model IDs, API base, protocol (`openai`,
`gemini`, or `anthropic`), limits, and quota-scope label. A configured or
discovered model does not become a production route until bounded validation
proves connectivity, requested-language output, structured schema
compatibility, grounding-compatible parsing, and bounded output behavior.

See [LLM routing](docs/llm-routing.md).

Run bounded validation before enabling routes in production:

```bash
uv run newsroom providers validate
uv run newsroom providers discover
uv run newsroom providers validate --discover
uv run newsroom providers status
```

Find source candidates for a subject without activating them:

```bash
uv run newsroom sources discover \
  --subject "Public health policy and epidemiology" \
  --platforms telegram,x,reddit,github,web \
  --mode quick
uv run newsroom sources candidates --status pending
uv run newsroom sources approve 17
```

Deep discovery uses a background Gemini Deep Research interaction and is polled
with `newsroom sources discovery-poll <job-id>`. See
[source discovery](docs/source-discovery.md).

## Telegram

Telegram output and Telegram ingestion use separate credentials.

For the output bot, configure these values in `.env`:

```dotenv
TELEGRAM_BOT_ENABLED=true
TELEGRAM_BOT_TOKEN=
TELEGRAM_AUTHORIZED_USER_IDS=
TELEGRAM_CHAT_ID=
```

For MTProto ingestion, add a dedicated Telegram application and account:

```dotenv
TELEGRAM_INGESTOR_ENABLED=true
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_PHONE=
```

Authorize the persistent session once:

```bash
docker compose --profile authorize run --rm telegram-authorize
```

The session lives in a Docker volume and must never be committed or shared.
SOCKS5, HTTP, obfuscated Telethon, and explicitly configured MTProxy routes
are supported.

## Bot controls

The owner-restricted bot exposes:

```text
/start
/help
/report
/report new
/report comprehensive
/report telegram|x|web|github|reddit
/latest
/status
/collect
/schedule
/settings
/sources
```

Runtime settings survive restarts:

```text
/settings language en|fa
/settings count 1..50
/settings schedule HH:MM,HH:MM
/settings schedule off
/settings sources all|telegram,x,web,github,reddit
```

## Development

```bash
uv sync --frozen --extra dev --extra telegram
docker compose up -d --wait postgres
uv run alembic upgrade head
uv run ruff check src tests
uv run mypy src/newsroom
uv run pytest tests -m "not integration"
uv run pytest tests/integration
docker compose config --quiet
uv run python scripts/audit_public_release.py
```

Live provider and platform checks are explicit opt-in operations and must use
only ignored local configuration.

## Production

Before exposing a deployment:

1. Run bootstrap with the intended source mode.
2. Replace all placeholder values and use a strong database password.
3. Configure only the integrations you intend to operate.
4. Validate provider models and authenticated collectors with bounded reads.
5. Back up PostgreSQL and Docker volumes.
6. Run `docker compose up -d --build --wait`.
7. Run the public and runtime exposure audit.

Detailed instructions are in [deployment](docs/deployment.md).

## Project structure

```text
src/newsroom/
  cli/          command adapters
  control/      owner settings and source catalog interface
  delivery/     Telegram bot, localization, and idempotent delivery
  editorial/    evidence, prompts, grounding, hierarchy, and LLM router
  pipeline/     collection, processing, report, and delivery orchestration
  processing/   normalization, deduplication, clustering, and evidence
  resources/    credential-free starter resources
  sources/      bounded source adapters and ingestion workers
  storage/      SQLAlchemy models, repositories, and Alembic migrations
```

PostgreSQL is the durable coordination seam. External platforms sit behind
bounded adapters. Callers use the control, collection, editorial, and delivery
interfaces instead of reaching into provider or storage details.

See [architecture](docs/architecture.md) and
[development](docs/development.md).

## Security and content rights

Run:

```bash
uv run python scripts/audit_public_release.py --history
uv run python scripts/audit_public_release.py --runtime
```

The audit checks tracked paths, locally configured protected values, Git
history, runtime logs, PostgreSQL, and the repository's English-only source
policy without printing secret values.

Read [SECURITY.md](SECURITY.md) before reporting a vulnerability. The MIT
license covers project code and original documentation only. Collected content,
provider output, platform data, cookies, sessions, and private source
inventories retain their own rights and restrictions.

## License

[MIT](LICENSE)
