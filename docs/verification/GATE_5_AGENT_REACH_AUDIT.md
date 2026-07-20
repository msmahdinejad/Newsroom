# Gate 5 — Agent-Reach Upstream Audit

**Audit date:** 2026-07-18
**Auditor:** Qwen Code (Gate 5 implementation)
**Repository:** https://github.com/Panniantong/Agent-Reach
**Pinned revision:** commit `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (2026-07-17)
**Pinned release:** v1.5.0 (per `pyproject.toml` `version`)
**License:** MIT (per `LICENSE` file — see `agent_reach_audit/LICENSE`)

## 1. Repository inspection

The upstream repository was cloned locally to `agent_reach_audit/` (gitignored) for inspection without vendoring its full history into the Newsroom repository.

- Default branch: `main`
- Latest commit on `main`: `1494c2ab239e7355a77e7cceaf3271453a1f34b5`
- Commit date: 2026-07-17
- License: MIT
- Python package: yes (`pyproject.toml`)
- CLI entry point: `agent-reach` (per `pyproject.toml [project.scripts]`)

## 2. Installation scripts

Agent-Reach is installable as a standard Python package:

- `pip install .` (from a local clone) — used in the isolated venv at `.agent-reach-venv/`
- `pip install git+https://github.com/Panniantong/Agent-Reach.git@1494c2a#egg=agent-reach` — pinned-commit install form (not used in production; we install from the audited local clone)
- No curl-to-shell or arbitrary remote installation scripts are run blindly
- No `sudo` / admin escalation required for the Python install itself
- The CLI is registered via the standard `console_scripts` entry point

## 3. Package dependencies

From `pyproject.toml [project.dependencies]`:

- `httpx` — HTTP client for upstream calls
- `feedparser` — RSS/Atom parsing
- `beautifulsoup4` — HTML parsing
- `markdownify` — HTML to Markdown
- `pyyaml` — configuration parsing
- `python-dotenv` — env file loading

All dependencies are standard, well-known Python packages. No exotic or untrusted dependencies observed.

## 4. Security documentation

The upstream `SECURITY.md` describes:

- the credential/cookie storage approach (per-platform credential files under the local Agent-Reach config dir, NOT in the database);
- subprocess/shell execution policy (the CLI spawns upstream tools like `yt-dlp`, `gh`, etc.);
- recommended account isolation (dedicated operational accounts for authenticated platforms);
- permissions model (local config dir with restrictive permissions);
- no built-in sandboxing (the Newsroom provides the isolation via the `agent-reach-worker` Docker service).

## 5. Supported channels

From `agent_reach/channels/` (18 channel modules):

- `web` (Jina Reader / curl) — tier 0
- `rss` (feedparser) — tier 0
- `github` (gh CLI) — tier 0
- `youtube` (yt-dlp) — tier 0
- `v2ex` (V2EX API) — tier 0
- `exa_search` (Exa) — tier 0
- `twitter` (X) — tier 1 (cookies or OpenCLI)
- `reddit` (rdt-cli) — tier 1 (login)
- `linkedin` (browser) — tier 2 (logged-in automation)
- `instagram` (browser) — tier 2 (logged-in)
- `facebook` (browser) — tier 2 (logged-in)
- `xiaohongshu` (browser) — tier 2 (logged-in)
- `bilibili` (B站 search API) — tier 1
- `xiaoyuzhou` (小宇宙 podcast) — tier 1
- `xueqiu` (雪球) — tier 1

## 6. Credential storage

Agent-Reach stores per-platform credentials under its local config dir (`~/.agent-reach/` by default; `./data/agent-reach/` in the Newsroom worker). Credentials are NOT stored in the database.

Newsroom production policy:

- the `agent-reach-worker` container uses `/data/agent-reach` (isolated Docker volume, file permissions 600);
- the Telegram MTProto session volume is NOT mounted into the worker;
- the editorial API key, Telegram Bot Token, and Telegram API hash are NOT passed to the worker;
- the host's primary browser profile is NEVER mounted;
- Agent-Reach config files are never committed and never baked into images.

## 7. CLI and doctor subcommand

The CLI is `agent-reach`. `agent-reach doctor --json` produces a flat JSON object of channel records, each with:

- `status`: `ok` / `warn` / `off` / `error`
- `active_backend`: string or null
- `backends`: list of known backends
- `tier`: 0 / 1 / 2
- `message`: human-readable status
- `name`: channel name

The Newsroom `AgentReachCapabilityRegistry` parses this output defensively into a typed registry. A channel is not production-ready just because the executable exists — `production_ready` flips to True only after a bounded real read succeeds.

## 8. Backends used per channel (doctor output, 2026-07-18)

| Channel | Status | Active backend | Tier | Notes |
|---|---|---|---|---|
| web | ok | Jina Reader | 0 | No auth needed |
| rss | ok | feedparser | 0 | No auth needed |
| github | warn | gh CLI | 0 | Installed; gh CLI timeout during probe |
| youtube | warn | yt-dlp | 0 | Installed; needs JS runtime for full probe |
| v2ex | ok | V2EX API | 0 | Not in Newsroom allowlist |
| exa_search | ok | Exa | 0 | Not in Newsroom allowlist |
| twitter (x) | off | — | 1 | No cookies / OpenCLI configured |
| reddit | off | — | 1 | No rdt-cli login configured |
| linkedin | off | — | 2 | No logged-in browser session |
| instagram | off | — | 2 | No logged-in browser session |
| facebook | off | — | 2 | No logged-in browser session |
| xiaohongshu | off | — | 2 | No logged-in browser session |
| bilibili | ok | B站 search API | 1 | Not in Newsroom allowlist |
| xiaoyuzhou (podcast) | ok | 小宇宙 API | 1 | Not in Newsroom allowlist |
| xueqiu | off | — | 1 | No auth configured |

## 9. Subprocess and shell execution paths

Agent-Reach spawns upstream tools via `subprocess` with shell=False for the following channels in the Newsroom allowlist:

- `web` — `curl https://r.jina.ai/<URL>` (bounded to r.jina.ai by the Newsroom controlled runner)
- `rss` — `feedparser.parse(URL)` in-process (no subprocess)
- `github` — `gh repo view`, `gh release view`, `gh release list`, `gh search repos`
- `youtube` — `yt-dlp --dump-json --flat-playlist <channel>`

The Newsroom `ControlledRunner` enforces shell=False, an executable allowlist, an operation allowlist, URL/identifier validation, a sanitized environment, bounded output, and child-process termination on timeout. Source content and editorial AI never produce commands.

## 10. Uninstall behavior

Standard pip uninstall: `pip uninstall agent-reach` removes the package. The local config dir (`.agent-reach/`) is left in place and must be removed manually if desired.

## 11. Auto-update mechanism

Agent-Reach has NO auto-update mechanism. The Newsroom does NOT enable any auto-update; the pinned revision is recorded in `AGENT_REACH_PINNED_VERSION` and in the `agent_reach_backend_state.pinned_version` column. Updates require a manual re-audit and re-pin.

## 12. Known risks

- **`github` channel** shows `warn` status because the `gh CLI` probe timed out during doctor. The backend IS installed. Production use relies on the existing native GitHub release collector (`src/newsroom/sources/github.py`) for scheduled collection; the Agent-Reach `gh` adapter is used only for capability verification and curated repo discovery.
- **`youtube` channel** shows `warn` because the yt-dlp probe requires a JS runtime for full verification. The backend IS installed and bounded real-read verification succeeded (see `GATE_5_YOUTUBE.md`).
- **`x`, `reddit`, `linkedin`, `instagram`, `facebook`, `xiaohongshu`** channels are `off` because no authentication is configured. They are deferred or manual-discovery-only per the Gate 5 decisions.
- **Upstream mutability** — Agent-Reach is under active development. The pinned revision insulates the Newsroom from upstream changes. Re-pinning requires re-audit.

## 13. Update procedure

1. Re-clone the upstream repository to a fresh audit directory.
2. Re-inspect license, dependencies, security docs, channel modules, and CLI.
3. Identify the new commit SHA.
4. Install in a fresh isolated venv.
5. Run `agent-reach doctor --json` and verify channels.
6. Run the Gate 5 deterministic test suite against the new revision.
7. Run bounded real-read verification for web, RSS, GitHub, and YouTube.
8. Update `AGENT_REACH_PINNED_VERSION` in `.env.example` and `agent_reach_backend_state.pinned_version`.
9. Rebuild the `agent-reach-worker` Docker image.
10. Record the new audit in this file.

## 14. Selected channels for production

- **web** — production ingestion approved (allowlisted reading only)
- **rss** — production ingestion approved (existing native collector retained)
- **github** — production ingestion approved (existing native release collector retained)
- **youtube** — production ingestion approved (yt-dlp via Agent-Reach, bounded real-read verified)
- **search** — deferred (Exa search not yet bounded-real-read verified)
- **x, reddit, linkedin, instagram, facebook, tiktok, bilibili, xiaohongshu, v2ex, podcast, xueqiu** — see `GATE_5_SOCIAL_NETWORK_DECISIONS.md`
