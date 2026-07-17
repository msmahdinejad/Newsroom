# Gate 4 Qwen Takeover Audit

**Date:** 2026-07-17
**Agent:** Qwen Code (implementation agent)
**Purpose:** Repository takeover audit before Gate 4 live verification

## Starting state

| Item | Value |
|------|-------|
| Branch | `gate-4-ai-editorial` |
| Starting commit | `dac4c7d` — docs: add gate 4 ADRs and verification evidence |
| Working tree | Not fully clean — `.specify/` tooling metadata (hermes→qwen) and `.qwen/` untracked. No source-code changes. |

## Reported Gate 4 commits — verified reachable

| Commit | Subject | Verified |
|--------|---------|----------|
| `4d9079c` | feat: add editorial provider abstraction | Yes |
| `2c7ebe9` | test: add credential-independent editorial tests (50 scenarios) | Yes |
| `e622f7c` | test: add editorial postgres integration tests | Yes |
| `dac4c7d` | docs: add gate 4 ADRs and verification evidence | Yes (HEAD) |

## Verified components

| Component | Location | Status |
|-----------|----------|--------|
| Migration 0005 | `src/newsroom/storage/migrations/versions/0005_gate4_editorial.py` | Creates `editorial_attempts` + `editorial_health` tables; schema correct |
| EditorialProvider ABC | `src/newsroom/editorial/provider.py` | Present, provider-neutral interface |
| DeterministicEditorialProvider | `src/newsroom/editorial/deterministic_provider.py` | No-network fallback, 50 tests pass |
| OpenAICompatibleEditorialProvider | `src/newsroom/editorial/openai_provider.py` | Present — see discrepancies below |
| Evidence builder | `src/newsroom/editorial/evidence_builder.py` | Bounded evidence with stable ref IDs |
| Prompt builder | `src/newsroom/editorial/prompt.py` | System/evidence separation, anti-injection delimiters |
| Validation | `src/newsroom/editorial/validation.py` | Schema validation with bounded repair |
| Grounding | `src/newsroom/editorial/grounding.py` | Claim-to-evidence verification |
| Persistence | `src/newsroom/editorial/persistence.py` | Attempt records, cache key, health update |
| Orchestrator | `src/newsroom/editorial/orchestrator.py` | Coordinates provider → validate → ground → fallback |
| Editorial health | `src/newsroom/service_status.py` + `persistence.py` | Singleton health record |
| Pipeline runner integration | `src/newsroom/pipeline/runner.py` report stage | Calls `generate_editorial()` |
| ORM models | `src/newsroom/storage/models.py` | `EditorialAttempt` + `EditorialHealth` |
| Config | `src/newsroom/config.py` | All 17 `EDITORIAL_*` fields present |
| .env.example | `.env.example` | All 17 variables declared |
| Compose | `compose.yaml` | Partial — see discrepancies |
| .gitignore | `.gitignore` | `.env`, `*.session`, `data/sessions/` all ignored |

## Gate 2/3 regression check

Gate 4 commit `4d9079c` modified `tests/integration/test_gate2_schema.py` and `tests/integration/test_gate3_mtproto.py` — changes are only alembic version assertion updates to accept `0005_gate4_editorial`. No behavioral test changes. No source-code changes to `delivery/` or `sources/`. All Gate 2 and Gate 3 tests pass (347 total).

## Credential safety

- `.env` is **not** tracked by git (`git ls-files .env` returns empty).
- No `.env` credentials appear in any git commit (`git log --all -p -S "EDITORIAL_API_KEY" -- .env` returns empty).
- A rotated key is locally configured in `.env` (verified: `editorial_api_key: present`).
- API base: Google Generative Language OpenAI-compatible endpoint (verified: non-secret).
- No credentials printed during this audit.

## Current .env configuration (non-secret values only)

| Variable | Value/Status |
|----------|-------------|
| EDITORIAL_ENABLED | True |
| EDITORIAL_PROVIDER | openai_compatible |
| EDITORIAL_MODEL | set (not displayed) |
| EDITORIAL_API_BASE | https://generativelanguage.googleapis.com/v1beta/openai/ |
| EDITORIAL_API_KEY | present (not displayed) |
| EDITORIAL_FALLBACK_ENABLED | True |
| EDITORIAL_MAX_OUTPUT_TOKENS | 500000 |
| EDITORIAL_MAX_INPUT_TOKENS | 128000 |
| editorial_ready() | True |

## Verification documents — actual vs planned

| Document | Status |
|----------|--------|
| GATE_4_LIVE_EVIDENCE.md | Honestly "PENDING" — describes what will be tested |
| GATE_4_TEST_RESULTS.md | Matches actual test results (50+17=67 editorial, 347 total) |
| GATE_4_PRELIVE_CHECK.md | Describes checks — need to verify against actual behavior |
| Others (PROVIDER_ARCHITECTURE, etc.) | Described from implementation, generally accurate |

## Discrepancies found

### D-1: CRITICAL — Nested asyncio.run() in OpenAI provider

`OpenAICompatibleEditorialProvider.generate()` calls `asyncio.run(self._generate_async(request))`.
The pipeline runner calls `generate_editorial()` from within `_run_async()`, which runs inside
`asyncio.run()`. Calling `asyncio.run()` from within a running event loop raises
`RuntimeError`. The AI provider will fail through the pipeline path, always triggering
deterministic fallback.

**Fix:** Convert `_call_api` to use synchronous `httpx.Client` instead of `httpx.AsyncClient`.
Remove `asyncio.run()` wrapper. The `generate()` method is already synchronous in the interface.

### D-2: CRITICAL — Output token limit exceeds provider capability

`EDITORIAL_MAX_OUTPUT_TOKENS=500000` is configured. No OpenAI-compatible provider supports
500K output tokens in a single response. The API will reject this with a 400 error. The adapter
sends `request.max_output_tokens` directly without enforcing an effective limit.

**Fix:** Implement `effective_limit = min(configured_limit, provider_capability, application_safety_cap)`.
Record the effective value separately from the configured value.

### D-3: IMPORTANT — Cache check not implemented

`_check_cache()` in the orchestrator always returns `None`. The `find_cached_attempt()`
function exists in `persistence.py` but is never called. Cache idempotency is non-functional
through the orchestrator path.

**Fix:** Wire `_check_cache` to call `find_cached_attempt` using the computed cache key.

### D-4: IMPORTANT — report_mode not persisted

`EditorialAttempt` dataclass has no `report_mode` field. `persist_attempt()` sets
`report_mode=""`. The DB column is always empty despite the migration defaulting to "scheduled".

**Fix:** Add `report_mode` to `EditorialAttempt`, set it in `generate_editorial()`, persist it.

### D-5: IMPORTANT — Compose forwards only a subset of editorial vars

`compose.yaml` forwards only 8 of 17 `EDITORIAL_*` vars to the scheduler service.
Cost-control vars (max_stories, max_evidence, max_excerpt, max_input_tokens, max_output_tokens,
temperature, concurrency, budgets) rely on Settings defaults in Docker. Non-default `.env`
overrides for cost controls won't take effect in scheduled runs.

**Fix:** Forward all editorial vars in compose.yaml.

### D-6: MEDIUM — No URL-construction tests

The adapter constructs URLs via `f"{self._api_base}/chat/completions"` after `rstrip("/")`.
No tests verify URL joining with various base URLs (trailing slash, no slash, with path).

**Fix:** Add URL-construction tests.

### D-7: LOW — Grounding else-branch is dead code

The orchestrator grounding condition `provider.name != "deterministic" or attempt.fallback_used is False`
is always True. The `else` branch (skip grounding) never executes. Not a bug — grounding always
runs — but the code is misleading.

## Baseline verification results

| Check | Result |
|-------|--------|
| Full test suite | 347 passed (56.82s) |
| Editorial deterministic tests | 50 passed |
| PostgreSQL integration tests | 17 passed (includes 17 editorial) |
| Ruff (src, tests, scripts) | All checks passed |
| MyPy (src/newsroom) | Success: no issues in 59 source files |
| Compose config | Valid |
| .env tracked | No |
| Credentials in git history | None found |

## Immediate remediation items

1. Fix nested asyncio.run() in OpenAI provider (D-1) — blocks all live verification
2. Implement effective token limit enforcement (D-2) — blocks live calls
3. Wire cache check to use find_cached_attempt (D-3)
4. Add report_mode to EditorialAttempt and persist it (D-4)
5. Forward all editorial vars in compose.yaml (D-5)
6. Add URL-construction tests (D-6)

## Gate 4 status at takeover

**IMPLEMENTED BUT NOT VERIFIED** — prior agent's assessment confirmed.
Credential-independent implementation is complete and tested. Live verification has not
been performed. Two critical defects (D-1, D-2) must be fixed before any live provider call.
