# LLM routing

Editorial requests enter one bounded shared dispatcher. Map shards are queued
individually; reduction waits for validated map artifacts.

## Route order

```text
preferred validated model and healthy key
-> next healthy key
-> next validated model on the provider
-> provider circuit breaker
-> next validated provider
-> deterministic terminal fallback
```

The default provider preference is Gemini, Mistral, Groq, then NVIDIA.
Different validated models may be used for map, reduction, and schema repair.

## Validation

A route must pass:

1. connectivity;
2. requested-language output;
3. structured schema output;
4. grounding-compatible parsing;
5. bounded token and output behavior.

Only safe metadata is persisted: provider, model, status, latency, timestamps,
failure category, and capabilities.

Validate all configured routes, or a selected provider/model:

```bash
uv run newsroom providers validate
uv run newsroom providers validate --provider gemini --model gemini-2.5-flash
uv run newsroom providers validate --validate-keys
uv run newsroom providers status
```

Validation reads access values only from `.env.providers.local`. Command output
contains safe model health and key identifiers, never original access values.

## Key pools and quotas

Keys are represented outside the request adapter only by safe fingerprints.
The router tracks health, cooldown, failure count, last use, and successful
request count. Original values remain in `.env.providers.local`.

Rate admission uses estimated input tokens, request and daily budgets, minimum
spacing, and actual usage reconciliation. Quotas shared by a provider project
remain shared across its keys.

## Failure policy

- Authentication failures isolate the affected key.
- Rate limits honor `Retry-After` and cool the relevant bucket.
- Timeouts and server errors receive one bounded retry before rotation.
- Invalid model or parameter responses disable that route.
- Malformed schema receives one repair attempt through another validated route.
- Policy rejection receives at most one compatible alternate route.
- A provider circuit opens after repeated provider-level failures and recovers
  through one half-open probe.

Provider changes do not create duplicate reports, artifacts, or Telegram
messages.
