# Gate 5X — X/Twitter Security

**Date:** 2026-07-20
**Pinned Agent-Reach revision:** `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (v1.5.0)
**twitter-cli version:** v0.8.5 (Apache-2.0)

## 1. Credential isolation

### Auth token handling

- `TWITTER_AUTH_TOKEN` and `TWITTER_CT0` are read from the host environment (named by `source.config['auth_token_env']` and `source.config['ct0_env']`).
- They are passed via `extra_env` to the `ControlledRunner` ONLY for `user`, `user-posts`, and `tweet` operations.
- They NEVER enter:
  - the database (no cookie/token/auth_header/ct0 columns in `x_account_state` or any other table)
  - the Git repository (never committed)
  - the Docker image (never baked in)
  - logs (never logged; `redact_credentials` masks Bearer/Cookie/Authorization patterns)
  - health output (`agent_reach_worker_status` exposes no tokens)
  - the default sanitized environment (only passed via explicit `extra_env`)
- If the env vars are not set, the adapter raises `CollectionError(auth_not_configured)` — it never silently proceeds.

### Dedicated account requirement

- The owner must use a dedicated operational X account, never the primary account.
- The owner accepts X account restriction risk.

### No browser profile mount

- The full browser profile and host home directory are NEVER mounted into the `agent-reach-worker` container.
- Auth is via env vars only, not via browser cookies.

## 2. Controlled command boundary

The `twitter` executable is added to `EXECUTABLE_ALLOWLIST` with four read-only operations (`status`, `user`, `user-posts`, `tweet`). All operations emit JSON.

**Forbidden operations** (not in the allowlist, rejected by the runner):
- `search`, `post`, `reply`, `like`, `unlike`, `retweet`, `unretweet`, `follow`, `unfollow`, `bookmark`, `unbookmark`, `delete`, `quote`, `favorite`, `unfavorite`

The runner enforces:
- `shell=False` always
- argument arrays only (never command strings)
- `validate_x_handle` (1–15 alphanumeric + underscore, accepts leading `@`)
- `validate_x_post_id` (1–20 digits)
- sanitized environment (no inherited application secrets)
- timeout, bounded output (2 MiB), child-process termination on timeout

## 3. Prompt-injection isolation

All text collected from X is untrusted data:
- The `XTimelineCollector` never passes text as a command argument.
- The `_build_command` method assembles commands from typed application code only.
- The runner has no `execute_string`, `shell_command`, or `run_shell` method.
- A post saying "ignore previous instructions", "run this command", "read this local file", "send me your API key", "enable this source", or "change the trust score" remains inert source content.
- The content hash uses `x + post_id` (stable numeric ID), never the text — so injection text does not affect dedup.
- Verified by `test_prompt_injection_in_text_remains_data` and `test_prompt_injection_text_rejected_as_command`.

## 4. No credential persistence — verified

### Database

- `x_account_state` table has NO columns for `cookies`, `token`, `api_key`, `auth_header`, `browser_profile`, `password`, `ct0`, or `auth_token`.
- Verified by `test_no_credential_fields_in_x_account_state` (integration test).
- `source.config` carries env var NAMES (`TWITTER_AUTH_TOKEN`), not values. Verified by `test_source_config_no_token_values`.

### Source config

- `source.config['auth_token_env']` stores the env var NAME (`"TWITTER_AUTH_TOKEN"`), not the value.
- No actual token values appear in `source.config`. Verified by `test_auth_tokens_not_in_source_config`.

### Auth env passing

- Auth tokens are passed via `extra_env` to the controlled runner, not via args or the default environment.
- Verified by `test_auth_tokens_passed_only_via_extra_env` — checks that `extra_env` contains `TWITTER_AUTH_TOKEN` and `TWITTER_CT0` for `user`/`user-posts`/`tweet` calls.

### Logs

- Auth tokens never appear in collector output items. Verified by `test_auth_tokens_never_logged`.

## 5. Failure isolation

- A failing X account does not block other accounts in `collect_agent_reach_sources`.
- The collector catches `CollectionError`, `RunnerError`, and `SSRFError` per source; records the failure in `x_account_state` and the source's `consecutive_failures` / `health_status`; and continues to the next source.
- Rate-limit, challenge, auth-failure, timeout, not-found, and transient failures are classified separately for diagnosis.
- Temporary failure is NOT treated as deletion — failed posts are not removed; `health_status` degrades but the cursor and collected posts are preserved.
- Verified by `test_source_failure_isolated` and `test_rate_limit_recoverable`.

## 6. Live verification security scan (pending)

After live verification, the following will be scanned for cookie/credential leaks:
- Git diff (no `BEGIN PRIVATE KEY`, `sk-`, `gsk_`, Telegram bot tokens, `password=` literals)
- Docker container env (no tokens in `docker inspect`)
- Worker logs (no tokens in log output)
- DB (`x_account_state`, `sources.config`, `raw_items.raw_data` — no token values)
- Docs (no tokens in markdown files)
- Health output (`agent_reach_worker_status` — no tokens)

This scan is BLOCKED on live verification, which is pending owner auth configuration.
