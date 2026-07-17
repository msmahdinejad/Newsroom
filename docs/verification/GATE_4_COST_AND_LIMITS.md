# Gate 4 Cost and Resource Controls

## Status: VERIFIED

**Date:** 2026-07-17

## Configuration variables

| Variable | Default | Description |
|---|---|---|
| EDITORIAL_MAX_STORIES_PER_CALL | 15 | Maximum stories per editorial call |
| EDITORIAL_MAX_EVIDENCE_PER_STORY | 10 | Maximum evidence items per story |
| EDITORIAL_MAX_EXCERPT_LENGTH | 300 | Maximum excerpt length in chars |
| EDITORIAL_MAX_INPUT_TOKENS | 12000 | Maximum input tokens |
| EDITORIAL_MAX_OUTPUT_TOKENS | 4000 | Maximum output tokens |
| EDITORIAL_TIMEOUT_SECONDS | 60 | Request timeout |
| EDITORIAL_MAX_RETRIES | 2 | Bounded retry count |
| EDITORIAL_CONCURRENCY_LIMIT | 1 | Concurrency limit |
| EDITORIAL_SCHEDULED_RUN_BUDGET | 1 | Model calls per scheduled run |
| EDITORIAL_MANUAL_RUN_BUDGET | 3 | Model calls per manual run |

## Effective limit enforcement (NEW)

The OpenAI-compatible adapter now enforces safe effective limits:

```python
effective_limit = min(configured_limit, provider_capability, application_safety_cap)
```

| Parameter | Value |
|-----------|-------|
| PROVIDER_MAX_OUTPUT_TOKENS_CAP | 8,192 |
| APP_SAFETY_OUTPUT_CAP | 8,192 |
| APP_SAFETY_INPUT_CAP | 128,000 |
| PROVIDER_MIN_TOKENS | 1 |

### How it works

- The configured value is retained for audit (`provider.configured_max_output_tokens`)
- The effective value is calculated separately (`provider.effective_max_output_tokens`)
- The API payload uses the effective value, never the raw configured value
- Non-positive values are clamped to PROVIDER_MIN_TOKENS (1)
- This prevents sending impossible values (e.g., 500,000 output tokens) to the provider

### Live verification

The configured `EDITORIAL_MAX_OUTPUT_TOKENS=500000` was capped to 2,000 (for minimal call)
and the provider accepted it without error. The `configured_max_output_tokens` property
still returns 500,000 for audit purposes.

Tests: `TestEffectiveTokenLimits` (10 tests in `tests/test_editorial_adapter.py`)

## Bounding strategy

- Stories are ordered by importance_score desc, then created_at desc
- Only top N stories are included (max_stories_per_call)
- Each story gets at most max_evidence_per_story source items
- Excerpts are truncated to max_excerpt_length chars
- Total input size is bounded by max_input_tokens
- Output is validated against max_output_tokens

## When limits are reached

- Prioritize stories deterministically (importance + recency)
- Record omitted counts in editorial attempt
- Do not silently truncate in the middle of an evidence item
- Retain deterministic fallback

## Model call budget

- Scheduled runs: 1 model call per run
- Manual runs: 3 model calls per run
- The entire database is never sent to one model call

## Live token usage

| Call | Prompt tokens | Completion tokens | Total |
|------|-------------|-------------------|-------|
| Minimal call | 1,579 | 717 | 2,296 |
| English AI story | 1,528 | 774 | 2,302 |
| Persian tech story | 1,544 | 699 | 2,243 |
| GitHub release | 1,576 | 766 | 2,342 |
| Telegram sourced | 1,540 | 649 | 2,189 |
| Multi-source cluster | 1,964 | 828 | 2,792 |
| Conflicting evidence | 1,785 | 810 | 2,595 |
| Prompt injection | 1,574 | 728 | 2,302 |
| **Total** | **13,090** | **5,971** | **19,061** |
