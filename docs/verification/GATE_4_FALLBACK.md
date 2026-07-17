# Gate 4 Fallback Policy

## Fallback trigger

When `EDITORIAL_FALLBACK_ENABLED=true` (default), the system falls back to
the DeterministicEditorialProvider on any of:

- Invalid API key
- Provider unavailable
- Timeout
- Rate limit
- Malformed response
- Schema validation failure
- Unsupported claims (grounding failure)
- Context-length failure
- Partial provider response
- Safety refusal
- Network interruption
- Process restart

## Fallback labeling

- Report `generation_method` is set to `deterministic` when fallback is used
- Editorial attempt `status` is set to `fallback`
- `fallback_used` flag is True in the attempt record
- The report content says "تولید شده توسط سیستم خبرخوان (حالت پشتیبان)"
- The report is NOT labeled as AI-generated when fallback is used

## Fallback is NOT failure

- The deterministic provider always produces valid output
- The report is still delivered
- The editorial attempt records the failure category for diagnosis
- The health endpoint records fallback_count

## Without fallback

When `EDITORIAL_FALLBACK_ENABLED=false`:
- Provider errors raise EditorialError
- No report is generated on failure
- The pipeline records the error and continues
