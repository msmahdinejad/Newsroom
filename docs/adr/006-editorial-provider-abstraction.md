# ADR-006: Editorial Provider Abstraction

## Status
Accepted

## Context
Gate 4 adds an AI editorial layer that turns persisted evidence into Persian
reports. The pipeline must work autonomously with no LLM credentials, and must
also call an OpenAI-compatible endpoint when credentials are present. A direct
dependency on any vendor SDK would couple the pipeline to one provider and make
the deterministic path a second-class citizen.

## Decision
Define a single `EditorialProvider` ABC in
`src/newsroom/editorial/provider.py` and make all application code depend on it.
Ship two implementations:

- `DeterministicEditorialProvider` (`src/newsroom/editorial/deterministic_provider.py`)
  — no network, always available, wraps the existing Persian renderer. `name`
  is `"deterministic"`, `model_name` is `"deterministic-v1"`.
- `OpenAICompatibleEditorialProvider` (`src/newsroom/editorial/openai_provider.py`)
  — adapter over any endpoint that accepts the OpenAI `/chat/completions` schema.
  Uses `httpx` only; no vendor SDK. `name` is `"openai_compatible"`.

`select_provider()` in `src/newsroom/editorial/orchestrator.py` returns the AI
adapter when `settings.editorial_ready()` and credentials exist, otherwise the
deterministic provider. The factory `create_provider_from_settings()` reads
`api_base`, `api_key`, `model`, `timeout`, `max_retries`, `temperature`, and
`max_output_tokens` from the environment only.

The interface carries structured `EditorialRequest` / `EditorialResponse`,
model metadata, timeout, bounded retries, usage, latency, finish status, and
typed `EditorialErrorCategory`. No vendor-specific types cross the boundary.

## Rationale
- Provider-neutral boundary lets the deterministic path and the AI path share
  one orchestrator, one validator, and one grounding check.
- `httpx` is already a dependency; adding the OpenAI Python SDK would import
  auth, retry, and typing machinery we do not need.
- Any OpenAI-compatible endpoint (local, OpenAI, Azure-compatible, open-weight
  gateways) works with zero code change — only environment changes.
- The ABC is the only seam; swapping providers is one new subclass.

## Consequences
- All vendor-specific code lives inside `openai_provider.py`. Anything outside
  the adapter depends on `EditorialProvider`, not on `httpx` or OpenAI types.
- Adding a non-OpenAI provider means a new subclass of `EditorialProvider`; the
  orchestrator, validation, and grounding layers are untouched.
- `OpenAICompatibleEditorialProvider` is synchronous-via-`asyncio.run` because
  the pipeline runner is sync; an async runner would call `_generate_async`
  directly.
- API keys are read from the environment and never logged.
