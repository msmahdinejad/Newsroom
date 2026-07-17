# Gate 4 Provider Architecture

## EditorialProvider ABC

Location: `src/newsroom/editorial/provider.py`

```python
class EditorialProvider(abc.ABC):
    @property
    @abc.abstractmethod
    def name(self) -> str: ...
    @property
    @abc.abstractmethod
    def model_name(self) -> str: ...
    @abc.abstractmethod
    def generate(self, request: EditorialRequest) -> EditorialResponse: ...
```

## Adapters

### DeterministicEditorialProvider
- File: `src/newsroom/editorial/deterministic_provider.py`
- No network, always available
- Wraps existing Persian renderer logic into structured EditorialOutput
- `name = "deterministic"`, `model_name = "deterministic-v1"`

### OpenAICompatibleEditorialProvider
- File: `src/newsroom/editorial/openai_provider.py`
- Uses httpx (already a dependency), no vendor SDK
- Configurable base URL, model, API key from environment only
- Supports `response_format: json_object` for structured output
- Bounded retries with exponential backoff on transient errors
- Typed error categories: timeout, rate_limit, provider_unavailable, etc.

## Provider selection

`select_provider()` in `src/newsroom/editorial/orchestrator.py`:
- Returns AI provider when `settings.editorial_ready()` and credentials exist
- Falls back to DeterministicEditorialProvider otherwise

## Error categories

`EditorialErrorCategory` enum:
- INVALID_API_KEY, PROVIDER_UNAVAILABLE, TIMEOUT, RATE_LIMIT
- MALFORMED_RESPONSE, SCHEMA_VALIDATION, UNSUPPORTED_CLAIMS
- CONTEXT_LENGTH, PARTIAL_RESPONSE, SAFETY_REFUSAL
- NETWORK_ERROR, UNKNOWN

## Retry policy

- Max retries from `EDITORIAL_MAX_RETRIES` (default 2)
- Exponential backoff: base * 2^attempt, capped at 30s
- Non-retryable: invalid_api_key, safety_refusal, schema_validation
- Retryable: timeout, rate_limit, provider_unavailable, network_error
