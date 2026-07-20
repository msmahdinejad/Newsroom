# Gate 5 — Agent-Reach Capabilities

**Audit date:** 2026-07-18
**Pinned revision:** `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (v1.5.0)
**Doctor output:** `GATE_5_DOCTOR_OUTPUT.json`

## 1. Capability registry

The `AgentReachCapabilityRegistry` (`src/newsroom/sources/agent_reach/registry.py`) records per-channel:

- channel name
- enabled state
- Agent-Reach health (true/false)
- selected backend
- fallback backends
- authentication requirement
- whether suitable for unattended operation
- last successful check
- failure category
- degraded state
- production approval state (`approved` / `approved_with_auth` / `manual_discovery_only` / `deferred` / `rejected`)
- production_ready flag (True only after a bounded real read succeeds)

The registry parses `agent-reach doctor --json` defensively. Doctor output shape mismatch leaves the registry in a consistent, empty state and records the parse error in `doctor_parse_error`.

## 2. Channels observed in doctor output (2026-07-18)

| Channel | Status | Active backend | Tier | Auth required | Unattended OK | Production approval |
|---|---|---|---|---|---|---|
| web | ok | Jina Reader | 0 | no | yes | approved |
| rss | ok | feedparser | 0 | no | yes | approved |
| github | warn | gh CLI | 0 | no | yes | approved |
| youtube | warn | yt-dlp | 0 | no | yes | approved (after bounded real read) |
| x (twitter) | off | — | 1 | yes | no | manual discovery only |
| reddit | off | — | 1 | yes | no | manual discovery only |
| linkedin | off | — | 2 | yes | no | manual discovery only |
| instagram | off | — | 2 | yes | no | deferred |
| facebook | off | — | 2 | yes | no | deferred |
| tiktok | off | — | — | — | — | deferred (not supported by pinned revision) |
| search (exa_search) | ok | Exa | 0 | no | yes | deferred (not bounded-real-read verified) |
| bilibili | ok | B站 search API | 1 | no | yes | deferred (not in Newsroom allowlist) |
| v2ex | ok | V2EX API | 0 | no | yes | deferred (not in Newsroom allowlist) |
| xiaoyuzhou (podcast) | ok | 小宇宙 API | 1 | no | yes | deferred (not in Newsroom allowlist) |
| xueqiu | off | — | 1 | yes | no | deferred |

## 3. Backends in use per channel

### web (Jina Reader)

- Selected backend: `Jina Reader` (via `curl https://r.jina.ai/<URL>`)
- Fallback backends: none listed
- Newsroom adapter: `WebPageReader` (`src/newsroom/sources/agent_reach/adapters.py`)
- SSRF protection: allowlisted public domains only, DNS validation, no private/loopback/link-local, no JS execution, no forms, no login, no unrestricted crawling, response-size limits, timeouts.

### rss (feedparser)

- Selected backend: `feedparser` (in-process Python library)
- Fallback backends: none listed
- Newsroom adapter: existing native RSS collector (`src/newsroom/sources/rss.py`) is retained for scheduled production collection. Agent-Reach's feedparser capability is used for capability verification only.

### github (gh CLI)

- Selected backend: `gh CLI`
- Fallback backends: none listed
- Newsroom adapter: existing native GitHub release collector (`src/newsroom/sources/github.py`) is retained for scheduled production collection. The Agent-Reach `GitHubDiscoveryCollector` (`gh search repos`) is used for curated repo discovery only.
- No duplicate release ingestion: the native collector pulls releases; the Agent-Reach adapter pulls discovery only.

### youtube (yt-dlp)

- Selected backend: `yt-dlp`
- Fallback backends: none listed
- Newsroom adapter: `YouTubeCollector` (`src/newsroom/sources/agent_reach/adapters.py`)
- Production scope: curated public channel allowlist, new video metadata only, durable per-channel cursor, dedup by video ID, optional public subtitle text when safely available.
- Out of scope: full video files, media archiving, comments, private videos, unlimited keyword discovery, arbitrary user-submitted URLs, enormous transcripts.

### x (twitter) — manual discovery only

- Selected backend: none (no auth configured)
- Fallback backends: `twitter-cli`, `OpenCLI`, `bird` (all require cookies)
- Newsroom adapter: `XPublicReadCollector` reads a single public post URL via Jina Reader (no cookies, no timeline monitoring).
- Production approval: `manual discovery only` until an explicit curated account list exists, durable cursors can be implemented, stable post IDs are returned, unattended operation is reliable, platform access is acceptable, dedicated authentication is locally configured, and a dedicated non-primary account is used when cookies are required.

### reddit — manual discovery only

- Selected backend: none (no login configured)
- Fallback backends: `rdt-cli` (requires login)
- Newsroom adapter: `RedditPublicReadCollector` reads a single public Reddit post URL via Jina Reader (no login, no subreddit monitoring).
- Production approval: `manual research capability only` until an explicit curated subreddit list exists, a stable authenticated backend passes real bounded tests, a dedicated account is configured, durable post and comment IDs are returned, bounded comment depth and result count are enforced, and unattended operation is reliable.

### linkedin — manual discovery only (public-page enrichment)

- Selected backend: none (no logged-in browser session)
- Newsroom adapter: `LinkedInPublicReadCollector` reads public LinkedIn pages via Jina Reader. Profile URLs, job URLs, and company URLs are rejected.
- Production approval: `public-page enrichment only, not scheduled production ingestion`.

### instagram / facebook / tiktok — deferred

- No safe bounded public-read backend in the pinned revision.
- Production approval: `deferred due to browser-session and operational-risk requirements`.

### search (Exa) — deferred

- Selected backend: `Exa` (via mcporter)
- Bounded real-read verification not yet performed in Gate 5.
- Production approval: `deferred` (pending bounded real-read verification).

### bilibili / v2ex / xiaoyuzhou (podcast) / xueqiu — deferred

- Backends are present (bilibili and v2ex are `ok`; xiaoyuzhou is `ok`; xueqiu is `off`).
- No documented unique-value case for the Persian AI and technology newsroom.
- Production approval: `deferred`.

## 4. Backend change visibility

Backend changes are visible in:

- `agent_reach_backend_state.selected_backend` and `agent_reach_backend_state.fallback_backends` (persisted).
- `agent_reach_backend_state.last_doctor_run_at` (timestamp of the last doctor run).
- `agent_reach_worker_status()` health output (safe fields only).

A newly selected upstream backend is NOT automatically accepted. Production approval requires:

1. compatibility and security checks (re-audit of the new backend);
2. a bounded real-read test that succeeds;
3. an explicit `production_approval` update via the registry.

## 5. Doctor parse robustness

The registry parser handles:

- flat JSON object of channel records (v1.5.0 shape);
- nested `{"channels": {...}}` shape (hypothetical future version);
- list of channel objects (hypothetical future version);
- malformed JSON, empty output, non-object top-level, missing channel records — all leave the registry consistent and record a `doctor_parse_error`.
- unknown channel names (e.g. `myspace`) are silently ignored.

## 6. Pinned-version mismatch handling

- `agent_reach_ready()` returns False when `AGENT_REACH_PINNED_VERSION` is empty.
- The controlled runner refuses to execute any subprocess when `agent_reach_ready()` is False.
- `agent_reach_backend_state.pinned_version` records the pinned revision per channel.
- A pinned-version mismatch between settings and the DB is a degraded state (not a hard failure); the worker reports it in `agent_reach_worker_status(degraded=["no_pinned_version"])`.
