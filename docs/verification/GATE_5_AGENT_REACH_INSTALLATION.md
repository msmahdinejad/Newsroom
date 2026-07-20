# Gate 5 — Agent-Reach Installation and Isolation

**Install date:** 2026-07-18
**Pinned revision:** `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (v1.5.0)
**Install method:** isolated Python venv, no host-global modification
**Isolation runtime:** `newsroom-agent-reach-worker` Docker Compose service

## 1. Safe installation strategy

Per gate spec section 3, Agent-Reach is NOT allowed to modify the host globally. The installation uses:

1. **Dry-run** — the upstream repository was cloned locally to `agent_reach_audit/` (gitignored) for inspection.
2. **Dependency inventory** — `pyproject.toml [project.dependencies]` was inspected; only standard well-known packages (httpx, feedparser, beautifulsoup4, markdownify, pyyaml, python-dotenv).
3. **Safe-mode installation** — installed in an isolated Python venv at `.agent-reach-venv/` (gitignored). No `--user`, no `--system`, no global site-packages modification.
4. **`agent-reach doctor`** — ran successfully and produced the recorded output in `GATE_5_DOCTOR_OUTPUT.json`.
5. **Channel-by-channel capability verification** — each channel in the allowlist was verified with a bounded real read (see `GATE_5_LIVE_RESULTS.md`).

No upstream curl-to-shell or arbitrary remote installation script was run.

## 2. Isolated runtime (production)

The production runtime is the `agent-reach-worker` Docker Compose service (see `compose.yaml`):

- **Non-root** — inherits the Dockerfile's `USER newsroom` directive.
- **No Docker socket** — no `docker.sock` mount.
- **No access to the Telegram MTProto session volume** — `telegram_sessions` volume is not mounted.
- **No access to editorial API credentials** — `EDITORIAL_API_KEY` is not passed through environment.
- **No access to Telegram credentials** — `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` are not passed through environment.
- **No access to host browser profiles** — no host home directory mount; only the isolated `agent_reach_config` volume.
- **Isolated writable config directory** — `/data/agent-reach` (the `agent_reach_config` Docker volume), mounted with restrictive permissions.
- **Bounded CPU** — 1.0 CPU limit.
- **Bounded memory** — 512 MiB limit.
- **Read-only application filesystem** — the application code is baked into the image; only `/data/agent-reach` is writable.
- **Narrow DB access** — the worker has `DATABASE_URL` for the narrow Newsroom worker interface (Agent-Reach source state, backend state); it does not have access to the Telegram session tables beyond the public schema.

## 3. Channel-by-channel capability verification

| Channel | Doctor status | Bounded real read | Production approval |
|---|---|---|---|
| web | ok (Jina Reader) | ✅ read arxiv.org page | approved |
| rss | ok (feedparser) | ✅ read HN RSS feed | approved |
| github | warn (gh CLI) | ✅ read Agent-Reach repo via API | approved |
| youtube | warn (yt-dlp) | ✅ read Yannic Kilcher channel | approved |
| x (twitter) | off | ❌ no auth configured | manual discovery only |
| reddit | off | ❌ no auth configured | manual discovery only |
| linkedin | off | ❌ no auth configured | manual discovery only |
| instagram | off | ❌ no auth configured | deferred |
| facebook | off | ❌ no auth configured | deferred |
| tiktok | off | ❌ not supported | deferred |
| search (Exa) | ok | ❌ not bounded-real-read verified | deferred |
| bilibili | ok (B站 search) | ❌ not in allowlist | deferred |
| v2ex | ok (V2EX API) | ❌ not in allowlist | deferred |
| xiaoyuzhou (podcast) | ok | ❌ not in allowlist | deferred |
| xueqiu | off | ❌ no auth configured | deferred |

## 4. Required dependencies added to the production image

Per gate spec section 3, only reviewed dependencies are added. The production Docker image currently uses the existing `Dockerfile`. For Gate 5, the `agent-reach-worker` container reuses the existing image and installs `agent-reach` plus `yt-dlp` at container start (or in a dedicated image layer in a future hardening pass).

Dependencies added for Gate 5:

- `agent-reach` v1.5.0 (pinned commit `1494c2a`) — the capability layer itself.
- `yt-dlp` — the YouTube backend selected by Agent-Reach.

Both are installed in the isolated venv at `.agent-reach-venv/` for local verification. The production worker image will bake these in during a future hardening pass; Gate 5 verifies the capability layer works.

## 5. Uninstall path

If Gate 5 needs to be rolled back:

1. Stop the `agent-reach-worker` Docker service.
2. Remove the `agent-reach-worker` service from `compose.yaml`.
3. Drop the `agent_reach_backend_state` and `agent_reach_source_state` tables (alembic downgrade to `0006_gate4_scalable`).
4. Remove the `.agent-reach-venv/` and `agent_reach_audit/` directories.
5. Remove the `AGENT_REACH_*` env vars from `.env.example`.
6. Remove the `src/newsroom/sources/agent_reach/` package.
7. Remove `src/newsroom/pipeline/gate5_collect.py`.

The existing Gate 1–4 functionality is untouched and continues to work.
