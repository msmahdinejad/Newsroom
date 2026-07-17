# Gate 4 Security

## No API key in database

The `editorial_attempts` table columns:
- provider, model, prompt_version, evidence_set_hash, schema_version
- started_at, completed_at, latency_ms, status, retry_count, fallback_used
- validation_result, grounding_result, usage, output_json
- error_category, error_summary (redacted), cache_key

No column stores API keys, tokens, or secrets.
Verified by integration test `test_no_api_key_in_attempt`.

## No API key in output JSON

The structured output JSON contains only editorial content.
Verified by integration test `test_no_api_key_in_output_json`.

## No API key in health output

`editorial_status()` returns provider name, model name, latency, counts, and budgets.
No key value, key fragment, or bearer token appears.
Verified by direct health endpoint test.

## No API key in logs

The OpenAI-compatible provider sends the key only as an Authorization header.
Error messages are truncated and redacted — no key value in error summaries.

## Untrusted-content isolation

All source content is treated as untrusted data:
- System instructions are separated from evidence data
- Evidence is serialized as JSON, not as executable prompt
- Stable delimiters prevent evidence from escaping its data section
- Security rules in the system prompt explicitly reject injection attempts
- Source content cannot change source trust, configuration, or output schema

## Secret scanning

- Git: clean (no .env tracked, no hardcoded keys)
- Docker context: clean (no secrets in Dockerfile or compose.yaml)
- Logs: clean (API key never printed)
- Database: clean (no key columns in editorial tables)
- Evidence documents: clean (no credentials in evidence packets)
