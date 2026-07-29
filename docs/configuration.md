# Configuration

Newsroom separates public templates from ignored local state.

## Files

| Public template | Ignored runtime file | Scope |
| --- | --- | --- |
| `.env.example` | `.env` | Application and integrations |
| `.env.providers.example` | `.env.providers.local` | Editorial providers |
| `.env.x.example` | `.env.x.local` | Isolated X authentication |

Run `python scripts/bootstrap.py --configuration-only` to create missing local
files without starting services. Existing files are never overwritten.

## Application settings

`.env` configures PostgreSQL, logging, collection bounds, scheduling,
Telegram, and optional workers. Integrations requiring credentials are
disabled in the public template.

Use a unique database password for every deployment. Keep the database port
bound to loopback unless a protected private network requires otherwise.

## Editorial providers

`.env.providers.local` is the canonical provider configuration. Each provider
accepts a comma-separated key pool and exact model IDs:

```dotenv
GEMINI_API_KEYS=
GEMINI_MODELS=
MISTRAL_API_KEYS=
MISTRAL_MODELS=
GROQ_API_KEYS=
GROQ_MODELS=
NVIDIA_API_KEYS=
NVIDIA_MODELS=
```

Additional compatible models may be configured. They remain disabled until
the validation workflow records the required capabilities. Do not add OCR,
transcription, or search credentials as editorial fallback providers.

Additional provider names may be added to `LLM_PROVIDER_ORDER`. Each uses the
same upper-case variable convention and declares `NAME_PROTOCOL` as `openai`,
`gemini`, or `anthropic`. Protocol support is code-owned; provider and model
catalogs are configuration-owned.

Discovering model IDs is read-only and does not enable routes:

```bash
uv run newsroom providers discover
uv run newsroom providers validate --discover
```

## Digest definitions

Named digests live in PostgreSQL, not `.env`. Each owns its subject, language,
timezone, source selection, report size, Telegram minimum, and local schedule.
Use `newsroom digests list|show|create|update|enable|disable`. `.env` contains
only bootstrap defaults and process-level bounds.

## Telegram output

Create a bot through BotFather and configure:

```dotenv
TELEGRAM_BOT_ENABLED=true
TELEGRAM_BOT_TOKEN=
TELEGRAM_AUTHORIZED_USER_IDS=
TELEGRAM_CHAT_ID=
```

Only authorized numeric user IDs can execute commands.

## Telegram ingestion

Create a Telegram application for a dedicated account:

```dotenv
TELEGRAM_INGESTOR_ENABLED=true
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_PHONE=
TELEGRAM_CONNECTION_MODE=direct
```

Supported connection modes are direct, abridged, intermediate, full,
obfuscated, and explicit MTProxy. Regular proxy URLs may use SOCKS5 or HTTP.
Keep usernames, passwords, endpoints, and MTProxy secrets only in `.env`.

Authorize once with the Compose `authorize` profile. Do not delete or recreate
an existing session during network diagnosis.

## X authentication

Copy `.env.x.example` to `.env.x.local` and add cookies for a dedicated
operational account. Enable authenticated collection explicitly in `.env`.
The file is loaded only by the isolated social worker.

## Models, quotas, and proxies

Quota settings describe the operator's actual provider account. Multiple keys
must not be treated as multiplied project capacity unless they have distinct
verified quota scopes. Shared egress proxies belong in the local provider file.

Never put credentials in Compose, source files, documentation, issue reports,
shell history, or command-line arguments.
