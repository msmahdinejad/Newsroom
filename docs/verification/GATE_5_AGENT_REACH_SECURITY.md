# Gate 5 — Agent-Reach Security

**Audit date:** 2026-07-18
**Pinned revision:** `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (v1.5.0)

## 1. Controlled command runner

The only path that executes Agent-Reach or its upstream backends is `src/newsroom/sources/agent_reach/runner.py` — the `ControlledRunner` class. It enforces:

- **`shell=False` always** — argument arrays only, never command strings.
- **Fixed executable allowlist** — `agent-reach`, `yt-dlp`, `gh`, `curl`, `python`, `python3`. Anything else is rejected with `RunnerError(category="executable_not_allowed")`.
- **Fixed operation allowlist per executable** — e.g. `yt-dlp` may run `dump-json`, `list-subs`, `write-subs`; `agent-reach` may run `doctor` and bounded `configure`. Anything else is rejected with `RunnerError(category="operation_not_allowed")`.
- **Per-argument validation**:
  - URLs: must be `http(s)`, no control characters, no newline injection, max 4096 chars.
  - YouTube video IDs: 11 chars from `[A-Za-z0-9_-]`.
  - YouTube channel IDs: `UC` + 22 chars.
  - Repo identifiers: `owner/name` with safe-identifier segments.
  - Queries: control chars and newlines rejected, max 256 chars.
- **Sanitized environment** — only keys in `ALLOWED_ENV_KEYS` pass through. `TELEGRAM_BOT_TOKEN`, `EDITORIAL_API_KEY`, `TELEGRAM_API_HASH`, and any other application secrets are NEVER inherited. `AGENT_REACH_CONFIG_DIR` is set explicitly from settings.
- **Timeout enforcement** — `subprocess.communicate(timeout=settings.agent_reach_timeout_seconds)`.
- **Bounded stdout/stderr** — truncated to `settings.agent_reach_max_output_bytes` (2 MiB default); `truncated=True` flag set on the result.
- **Child-process termination on timeout** — POSIX process-group SIGTERM → SIGKILL; Windows leaf PID terminate → kill.
- **Credential redaction** — `redact_credentials()` masks Bearer tokens, `sk-` keys, `gsk_` keys, Telegram bot tokens, and Cookie/Authorization headers before logging.
- **curl restricted to r.jina.ai** — the runner statically rejects any curl invocation whose args do not include `r.jina.ai`.

## 2. Prompt-injection isolation

All text collected by Agent-Reach and its upstream tools is untrusted data. The Newsroom enforces:

- Source content never reaches the runner as a command argument. The runner's `_build_command` is the only place commands are assembled, and it uses only typed application code.
- The editorial AI never produces executable Agent-Reach commands. The runner has no `execute_string`, `shell_command`, or `run_shell` method — the only entry point is `run(executable, operation, fixed_args)`.
- A social post saying "run this command", "ignore previous instructions", "read this local file", "send me your API key", "enable this source", or "change the trust score" remains inert source content.
- Adversarial fixtures in `tests/test_agent_reach.py` cover command injection and agent-instruction injection.

## 3. Credential isolation

- **No credential persistence in the database** — `agent_reach_backend_state` and `agent_reach_source_state` tables have NO columns for cookies, tokens, API keys, authorization headers, or browser-profile paths. Verified by `test_no_cookie_field_in_backend_state_model` and `test_no_cookie_field_in_source_state_model`.
- **No credential persistence in source config** — `source.config` carries adapter config (channel_id, max_items, allowed_domains) but never cookies or tokens. Verified by `test_source_config_does_not_persist_credentials`.
- **Isolated config directory** — the `agent-reach-worker` container uses `/data/agent-reach` (isolated Docker volume), NOT the host home directory.
- **No shared Telegram session** — the `telegram_sessions` Docker volume is NOT mounted into the worker.
- **No shared editorial credentials** — `EDITORIAL_API_KEY` is NOT passed to the worker.
- **No shared Telegram credentials** — `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` are NOT passed to the worker.
- **No host browser profile mount** — the host home directory is NEVER mounted.
- **No credentials in health output** — `agent_reach_worker_status()` exposes only enabled, pinned_version, allowed_channels, allow_authenticated, db_connected, and per-channel safe fields (selected_backend, healthy, degraded, production_ready, production_approval, last_success_at, last_failure_category). Never cookies, tokens, browser-profile paths, command environments, or full command output.
- **No credentials in Docker images** — no credentials baked into the image.
- **No Agent-Reach config in the repo** — `.gitignore` excludes `data/agent-reach/` and `.agent-reach-venv/`.

## 4. Authentication policy

- `AGENT_REACH_ALLOW_AUTHENTICATED_CHANNELS` defaults to `false`.
- The `AUTHENTICATED_OPERATIONS` set lists operations that require authentication (currently `agent-reach:configure`).
- When the flag is false, authenticated operations are rejected with `RunnerError(category="authentication_required")`.
- When the flag is true (owner opt-in), dedicated operational accounts must be used — never the owner's primary account.

## 5. Web SSRF protection

The web adapter (`WebPageReader`) enforces:

- **Allowlisted public domains only** — `DEFAULT_WEB_ALLOWED_DOMAINS` plus per-source `config.allowed_domains`.
- **No private/loopback/link-local destinations** — `_validate_public_url` rejects `127.x`, `10.x`, `192.168.x`, `169.254.x`, `0.x`, `::1`, `fc..`, `fd..` (both raw IP literals and DNS-resolved addresses).
- **DNS resolution validation** — `socket.getaddrinfo` is called; if any A/AAAA record resolves to a private address, the URL is rejected.
- **No JavaScript execution** — Jina Reader returns markdown/text, not rendered HTML.
- **No form submission, no login, no unrestricted crawling** — only single-URL reads.
- **Response-size limits** — controlled runner caps stdout at 2 MiB; the adapter truncates content to 8000 chars.
- **Timeouts** — controlled runner enforces `AGENT_REACH_TIMEOUT_SECONDS`.
- **Redirect-based SSRF** — Jina Reader returns the final URL in a header; `_validate_redirect_target` re-validates that the redirect target is still public and (when configured) still inside the allowed-hosts set.

## 6. Source-failure isolation

A failing Agent-Reach source never blocks other sources and never breaks the rest of the pipeline:

- `collect_agent_reach_sources` catches `CollectionError`, `RunnerError`, and `SSRFError` per source; records the failure in `agent_reach_source_state` and in the source's `consecutive_failures` / `health_status`; and continues to the next source.
- After 3 consecutive failures, the source's `health_status` flips to `degraded`.
- Verified by `test_source_failure_does_not_stop_other_sources` and the integration test `test_source_failure_does_not_block_other_sources`.

## 7. Deterministic credential-independent tests

103 tests in `tests/test_agent_reach.py` cover the full security boundary with fake command runners and recorded public fixtures — no real subprocesses, no network, no credentials. See `GATE_5_TEST_RESULTS.md` for the full coverage matrix.

## 8. PostgreSQL integration tests

23 tests in `tests/integration/test_gate5_agent_reach.py` verify the persistence layer with real PostgreSQL — no cookie / token / auth-header persistence, transaction rollback, durable cursor, restart continuation, and index usage. See `GATE_5_TEST_RESULTS.md`.

## 9. Secret scanning

Before every commit:

- `git diff` is inspected.
- `ruff check` is run.
- `mypy` is run.
- secret scanning is performed (no `BEGIN PRIVATE KEY`, no `sk-`/`gsk_` keys, no Telegram bot tokens, no `password=` literals in the diff).
- `.env` is verified untracked.
- Agent-Reach config (`data/agent-reach/`) is verified untracked.
- Telegram sessions (`data/sessions/`) are verified untracked.
- `.qwen/` and `.specify/` local tooling files are verified untouched.
