# ADR-009: AI Failure and Deterministic Fallback

## Status
Accepted
Supersedes ADR-005 (Deterministic Fallback Editorial) for the Gate 4 provider
interface; ADR-005's rationale still holds for the fallback path itself.

## Context
The AI provider can fail in many ways: bad key, rate limit, timeout, malformed
JSON, schema validation failure, grounding failure, safety refusal, or an
unknown error. The pipeline runs autonomously on a schedule and must never
block on an LLM outage. A report is better than no report, as long as the
report is honestly labeled.

## Decision
Define typed error categories, a single fallback policy, and explicit
fallback labeling.

- `EditorialErrorCategory` in `src/newsroom/editorial/schema.py` is a `StrEnum`
  with 12 categories: `INVALID_API_KEY`, `PROVIDER_UNAVAILABLE`, `TIMEOUT`,
  `RATE_LIMIT`, `MALFORMED_RESPONSE`, `SCHEMA_VALIDATION`, `UNSUPPORTED_CLAIMS`,
  `CONTEXT_LENGTH`, `PARTIAL_RESPONSE`, `SAFETY_REFUSAL`, `NETWORK_ERROR`,
  `UNKNOWN`.
- `EditorialError` carries `category`, `detail` (truncated to 500 chars), and
  `retryable`. `OpenAICompatibleEditorialProvider` maps HTTP and parse failures
  to these categories and sets `retryable` per category (e.g. `RATE_LIMIT` and
  `TIMEOUT` are retryable; `INVALID_API_KEY` and `SAFETY_REFUSAL` are not).
- Bounded retries: the adapter retries up to `max_retries` with exponential
  backoff capped at 30s, only for `retryable` errors.
- Fallback policy in `generate_editorial()`
  (`src/newsroom/editorial/orchestrator.py`): on `EditorialError`,
  schema-validation failure, or grounding failure, if
  `settings.editorial_fallback_enabled` is true, the orchestrator calls
  `DeterministicEditorialProvider.generate()` with the same `EditorialRequest`,
  sets `attempt.fallback_used = True` and `attempt.status = "fallback"`, and
  records the original `error_category` and `error_summary` on the attempt.
- Fallback labeling: `EditorialAttempt.status` is one of
  `ok / fallback / validation_failed / grounding_failed / provider_error`.
  The rendered report labels AI output as "تولید شده توسط هوش مصنوعی",
  deterministic output as "تولید شده توسط سیستم خبرخوان", and fallback output
  as "تولید شده توسط سیستم خبرخوان (حالت پشتیبان)". `ReportMetadata.editorial_status`
  is `ok` or `fallback`.
- If fallback is disabled and the provider fails, the orchestrator re-raises
  the `EditorialError` so the pipeline runner can surface it.

## Rationale
- Typed categories let the orchestrator decide retry vs. fallback without
  parsing error strings.
- The deterministic provider is always available and network-free, so fallback
  is guaranteed to produce *something* as long as evidence exists.
- Explicit labeling keeps the user informed: a fallback report is honestly
  marked, never passed off as AI synthesis.
- Persisting `error_category` and `error_summary` on the attempt gives
  post-hoc debugging without re-running the provider.

## Consequences
- A fallback run still goes through grounding (re-grounded against the
  deterministic output) so the same trust rules apply.
- `fallback_used` and `editorial_status` are the two fields the delivery and
  audit layers use to distinguish paths; they must stay in sync.
- Retries are bounded by `max_retries` (default 2); a single editorial call
  cannot loop forever.
- Disabling fallback (`editorial_fallback_enabled = false`) makes provider
  failures fatal to that report cycle — appropriate for a strict-AI mode but
  not the default.
