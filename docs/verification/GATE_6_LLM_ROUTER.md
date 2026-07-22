# Gate 6 — Multi-provider Editorial Router

## Runtime architecture

The editorial boundary now uses one persistent router instead of a
single-provider client:

```text
editorial stage
  -> bounded shared dispatcher
  -> provider circuit breaker
  -> validated model route
  -> safe key pool
  -> project/model quota admission
  -> bounded HTTP request
  -> schema and grounding validation
  -> persisted safe attempt/usage/health metadata
  -> deterministic editorial fallback
```

Provider order is Gemini, Mistral, Groq, NVIDIA, then deterministic. Map jobs
enter the dispatcher separately. The final reduction waits for the required
validated map artifacts, and route-neutral artifact identities allow a failed
stage to resume through another provider without duplicating completed work.

Provider access is loaded only from the ignored `.env.providers.local`.
Neither application `.env` values nor ambient provider variables are accepted
as provider access. Only one-way key fingerprints and operational counters are
persisted.

## Queue and quota policy

Gemini defaults to queue capacity 32, concurrency 1, and five-second minimum
request spacing. Its project-scoped capacity is admitted at 12 RPM, 200,000
TPM, and 450 RPD. Keys rotate for resilience but do not multiply the shared
project/model quota bucket. Estimated input usage is reserved before dispatch
and reconciled against actual returned usage.

The key pool uses least-recently-used/round-robin selection, bounded cooldowns,
invalid-key isolation, `Retry-After`, daily reset windows, one transient retry,
and model disablement for invalid-model responses. Provider circuits open
after three consecutive provider failures, remain open for five minutes by
default, and close only after a successful half-open probe.

Gemini 3.6 Flash and Gemini 3.5 Flash-Lite requests omit deprecated sampling
parameters. Structured-output repair is attempted once through a compatible
validated alternate route.

## Bounded live validation

Every candidate belonging to a locally configured provider was tested with a
minimal bounded request. A model was enabled only after connectivity, Persian
output, the required schema, grounding-compatible parsing, and bounded output
all passed.

| Provider | Model | Result |
|---|---|---|
| Gemini | `gemini-3.5-flash-lite` | validated |
| Gemini | `gemini-3.1-flash-lite` | validated |
| Gemini | `gemini-3.6-flash` | disabled: rate limit |
| Gemini | `gemini-3.5-flash` | disabled: server error |
| Gemini | `gemini-3-flash-preview` | disabled: malformed schema |
| Gemini | `gemini-2.5-flash` | disabled: invalid model on configured endpoint |
| Mistral | all requested candidates | unavailable: configured access invalid |
| Groq | all requested candidates | unavailable: no configured key |
| NVIDIA | requested candidate | unavailable: configured access invalid |

Unavailable optional providers are retained as disabled routes. Access values,
validation response bodies, and prompts are not stored in router health data.

## Persistent audit and restart behavior

PostgreSQL stores safe provider/model health, fingerprint-only key state,
quota state, circuit state, and provider-route attempts. Attempt lineage carries
the editorial job, stage, shard, artifact, report, actual provider/model,
latency, usage, status, and safe failure category. It never carries provider
access values.

Completed map/final artifacts, report identity, delivery identity, and Telegram
message IDs remain idempotent across provider changes and restarts. The
scheduled-delivery cursor advances only after all Telegram chunks are confirmed.
