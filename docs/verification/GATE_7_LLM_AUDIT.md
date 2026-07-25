# Gate 7 LLM Router Audit

## Runtime boundary

Editorial access values are loaded only from the ignored
`.env.providers.local`. The scheduler and owner bot receive that file
read-only; no other production service does. PostgreSQL stores only provider
names, model IDs, timestamps, usage, safe error categories, and SHA-256 key or
quota fingerprints. No access value, proxy credential, prompt, or response
secret is persisted or exposed through health output.

## Live validation matrix

| Provider | Configured values | Tested | Successful | Failed / unavailable | Enabled production models |
| --- | ---: | ---: | ---: | ---: | --- |
| Gemini | 6 | 6 | 1 | 5 invalid-account values | `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite` |
| Mistral | 2 | 2 | 0 | 2 invalid-account values | none |
| Groq | 0 | 0 | 0 | not configured | none |
| NVIDIA | 2 | 2 | 0 | 2 invalid-account values | none |

Every non-empty value received a bounded real validation result. Gemini
validated Persian structured-output and grounding-compatible parsing for both
enabled models. Gemini candidates `gemini-3.6-flash`, `gemini-3.5-flash`, and
`gemini-3-flash-preview` were disabled after malformed-schema validation;
`gemini-2.5-flash` was disabled as an invalid model. Mistral and NVIDIA routes
remain disabled after their provider-account failures. Groq is accurately
recorded as not configured, not as an authentication failure.

## Queue and resilience proof

Gemini uses a shared bounded queue of 32, concurrency one, five-second minimum
request spacing, and project-scoped effective quotas: 12 RPM, 200000 TPM, and
450 RPD. Map shards are admitted one at a time; final reduction waits for
validated map artifacts. Actual usage reconciles reserved tokens in PostgreSQL.

The deterministic router suite covers round-robin selection, cooldown and
return-to-first-key, project quota exhaustion, RPM/TPM/RPD admission,
backpressure, Gemini serialization/spacing, Retry-After, invalid-key isolation,
timeout/5xx retry, invalid-model disable, schema repair, circuit half-open
recovery, artifact reuse, and idempotent Telegram delivery. Gemini 3.6 Flash
and 3.5 Flash-Lite omit deprecated sampling parameters.

At final observation the durable key pool had six Gemini records (one enabled,
five disabled), two disabled Mistral records, and two disabled NVIDIA records;
values are never represented in this document. Gemini's circuit was closed;
the other providers were unavailable routes and therefore did not block report
generation.

## Fallback result

Live routing used Gemini because it was the only provider with a validated
access value. Live cross-provider fallback could not be exercised without a
second working provider; it is covered deterministically for Mistral, Groq,
and NVIDIA. The live Gemini provider-level failure/cooldown path was recovered
by a validated probe before the final scheduled report. Deterministic terminal
fallback remains available, but was not used by report 502.

## Delivered AI lineage

Scheduled report **502** completed with `generation_method=ai`, no fallback,
and no partial-AI label. Its 8 shards made 9 accepted model calls: seven map
artifacts and the final reduction on `gemini-3.5-flash-lite`, plus one
`gemini-3.1-flash-lite` schema-repair map artifact. It persisted 13 artifacts,
267 evidence-lineage rows, 61864 input tokens, and 17721 output tokens.
Delivery **465** persisted Telegram message ID **76** and advanced the
scheduled delivery cursor only after complete delivery.
