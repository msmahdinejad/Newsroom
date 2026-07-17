# Gate 4 Pre-Live Check

## Credential-independent checkpoint status

- Starting commit: `efb385b`
- Branch: `gate-4-ai-editorial`
- All 347 tests pass (280 existing + 50 editorial deterministic + 17 integration)
- Ruff: clean
- MyPy: clean (59 source files)
- Compose validates
- Deterministic reporting remains operational
- Gate 2 bot remains operational
- Gate 3 ingestion remains operational
- Secret scanning: clean (no API keys in git, code, or tests)
- Provider-disabled full-stack restart succeeds (editorial disabled = deterministic)

## Supported provider interface

`EditorialProvider` ABC in `src/newsroom/editorial/provider.py`:
- `generate(request: EditorialRequest) -> EditorialResponse`
- Properties: `name`, `model_name`

## Available adapters

1. `DeterministicEditorialProvider` — always available, no network
2. `OpenAICompatibleEditorialProvider` — configurable base URL, env-only API key

## Required environment-variable names

```
EDITORIAL_ENABLED=false
EDITORIAL_PROVIDER=deterministic
EDITORIAL_MODEL=
EDITORIAL_API_BASE=https://api.openai.com/v1
EDITORIAL_API_KEY=
EDITORIAL_TIMEOUT_SECONDS=60
EDITORIAL_MAX_RETRIES=2
EDITORIAL_MAX_INPUT_TOKENS=12000
EDITORIAL_MAX_OUTPUT_TOKENS=4000
EDITORIAL_TEMPERATURE=0.3
EDITORIAL_FALLBACK_ENABLED=true
```

## Model requirements

The selected model must support:
- Reliable Persian generation
- Structured JSON output (`response_format: json_object`)
- OpenAI-compatible chat completions API

## Configured input/output limits

- Max input tokens: 12000
- Max output tokens: 4000
- Max stories per call: 15
- Max evidence per story: 10
- Max excerpt length: 300 chars
- Timeout: 60 seconds
- Max retries: 2

## Secure local credential path

API key is read from `EDITORIAL_API_KEY` environment variable via `.env` file (gitignored).
Never printed, logged, or stored in the database.

## Status

PAUSED — awaiting user credential configuration.
