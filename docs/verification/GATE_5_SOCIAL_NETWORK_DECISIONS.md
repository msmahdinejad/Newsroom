# Gate 5 — Social Network Production Decisions

**Decision date:** 2026-07-18
**Pinned Agent-Reach revision:** `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (v1.5.0)

## 1. Decision framework

Each evaluated channel is classified into exactly one of:

- `production ingestion approved` — unattended scheduled collection with no authentication required.
- `production ingestion approved with dedicated authentication` — unattended scheduled collection with dedicated operational credentials (never the owner's primary account).
- `manual discovery only` — a human may use the capability for one-off research; no scheduled ingestion.
- `deferred` — capability is present but not yet verified or not yet useful for the Persian AI newsroom.
- `rejected` — capability is unsafe or unsuitable and will not be revisited.

A channel is NOT production-ready just because `agent-reach doctor` detects it. `production_ready` flips to True only after a bounded real read succeeds and the production-approval decision is recorded.

## 2. Channel decisions

### Web — `production ingestion approved`

- **Backend:** Jina Reader (via `curl https://r.jina.ai/<URL>`)
- **Scope:** allowlisted public domains only (see `DEFAULT_WEB_ALLOWED_DOMAINS` in `adapters.py`); per-source `config.allowed_domains` extends the allowlist.
- **SSRF protection:** private/loopback/link-local rejection, DNS resolution validation, redirect-based SSRF rejection, response-size limits, timeouts, no JS execution, no forms, no login, no unrestricted crawling.
- **Bounded real read:** ✅ read `https://arxiv.org/abs/2501.12948` (DeepSeek-R1 paper) — 8000 bytes.
- **Rationale:** safe, unauthenticated, allowlisted public-domain reading with strong SSRF protection.

### RSS — `production ingestion approved`

- **Backend:** feedparser (in-process Python library)
- **Scope:** existing native RSS collector (`src/newsroom/sources/rss.py`) is retained for scheduled production collection. Agent-Reach's feedparser capability is used for capability verification only — we do not replace working native RSS collection merely to route every request through Agent-Reach.
- **Bounded real read:** ✅ read `https://hnrss.org/frontpage` — 20 entries.
- **Rationale:** existing native RSS collector is better suited for scheduled production collection; Agent-Reach provides capability diagnostics only.

### GitHub — `production ingestion approved`

- **Backend:** gh CLI (for discovery); existing native GitHub release collector (`src/newsroom/sources/github.py`) for scheduled collection.
- **Scope:** curated repo discovery via `gh search repos`; release metadata via the existing native collector. No duplicate release ingestion through two connectors.
- **Bounded real read:** ✅ read `https://api.github.com/repos/Panniantong/Agent-Reach` — 57,704 stars.
- **Rationale:** existing native GitHub release collector is better suited for scheduled production collection; Agent-Reach provides discovery only.

### YouTube — `production ingestion approved`

- **Backend:** yt-dlp (selected by Agent-Reach).
- **Scope:** curated public channel allowlist; new video metadata only (title, description, publication timestamp, stable channel ID, stable video ID, canonical URL); optional public subtitle text when safely available; durable per-channel cursor; dedup by video ID.
- **Out of scope:** downloading full video files, archiving media, collecting comments, collecting private videos, unlimited keyword discovery, processing arbitrary user-submitted URLs, persisting enormous transcripts without limits.
- **Bounded real read:** ✅ read `https://www.youtube.com/@YannicKilcher/videos` — 3 video metadata entries; collected video `xHi8PUIVyoo` into the Newsroom pipeline; flowed through normalization, story creation, evidence, AI editorial, and Telegram delivery (message_id [41]).
- **Rationale:** safe, unauthenticated, bounded metadata-only reading from curated public channels. See `GATE_5_YOUTUBE.md` for full details.

### X / Twitter — `manual discovery only`

- **Backend:** none configured (cookies or OpenCLI required for monitoring).
- **Scope:** read a single public post URL via Jina Reader. No persistent authentication, no cookies, no timeline monitoring.
- **Production integration requirements (not met in Gate 5):** explicit curated account list; durable cursors; stable post IDs; unattended operation reliability; platform access acceptable to owner; dedicated non-primary account when cookies are required.
- **Bounded real read:** ❌ no auth configured.
- **Rationale:** reading one public URL does not prove reliable scheduled monitoring. Default classification: `available for manual discovery, deferred for unattended production ingestion`.
- **See:** `GATE_5_X.md`.

### Reddit — `manual discovery only`

- **Backend:** none configured (rdt-cli login required for subreddit monitoring).
- **Scope:** read a single public Reddit post URL via Jina Reader. No login, no subreddit monitoring.
- **Production integration requirements (not met in Gate 5):** explicit curated subreddit list; stable authenticated backend; dedicated account; durable post and comment IDs; bounded comment depth and result count; reliable unattended operation.
- **Bounded real read:** ❌ no auth configured.
- **Rationale:** login state required for subreddit monitoring. Default classification: `manual research capability only`.
- **See:** `GATE_5_REDDIT.md`.

### LinkedIn — `manual discovery only` (public-page enrichment)

- **Backend:** none configured (logged-in browser automation required for profile/job collection).
- **Scope:** read public LinkedIn pages via Jina Reader. Profile URLs (`/in/...`, `/pub/...`), job URLs (`/jobs/...`), and company URLs (`/company/...`) are rejected.
- **Bounded real read:** ❌ no auth configured.
- **Rationale:** public-page enrichment only; no logged-in browser automation for initial production. Default classification: `public-page enrichment only, not scheduled production ingestion`.

### Instagram — `deferred`

- **Backend:** none configured (logged-in browser session required).
- **Rationale:** browser-session and operational-risk requirements unmet. Default classification: `deferred due to browser-session and operational-risk requirements`.

### Facebook — `deferred`

- **Backend:** none configured (logged-in browser session required).
- **Rationale:** same as Instagram.

### TikTok — `deferred`

- **Backend:** not supported by the pinned Agent-Reach revision.
- **Rationale:** no safe bounded public-read backend. Deferred unless a future pinned revision explicitly supports a safe bounded public-read backend.

### Bilibili, XiaoHongShu, V2EX, XiaoYuZhou (podcast), XueQiu — `deferred`

- **Backends:** bilibili (ok, B站 search API), v2ex (ok, V2EX API), xiaoyuzhou (ok, 小宇宙 API), xueqiu (off), xiaohongshu (off).
- **Rationale:** no documented unique-value case for the Persian AI and technology newsroom. Not enabled merely because Agent-Reach supports them. Require a documented unique-value case and a curated source list.

### Search (Exa) — `deferred`

- **Backend:** Exa (via mcporter).
- **Rationale:** capability is present but bounded real-read verification was not performed in Gate 5. Deferred until verified.

## 3. Preferred fast-track outcome (realized)

The preferred initial production set is:

- Telegram through existing native MTProto ingestion ✅ (Gate 3, unchanged)
- RSS through existing native ingestion ✅ (Gate 1, unchanged)
- Websites through safe allowlisted reading ✅ (Gate 5)
- GitHub through existing native ingestion ✅ (Gate 1, unchanged)
- YouTube through Agent-Reach when live verification passes ✅ (Gate 5)
- Agent-Reach web/search capabilities for bounded discovery and enrichment — search deferred, web approved ✅ (Gate 5)

X is `manual discovery only` (not added to scheduled ingestion). Reddit is `manual research capability only`. Instagram, Facebook, LinkedIn authenticated access, and TikTok are `deferred`.

This matches the preferred scope from gate spec section 16.

## 4. Decision summary table

| Channel | Production approval | Bounded real read | Auth required |
|---|---|---|---|
| web | approved | ✅ | no |
| rss | approved | ✅ | no |
| github | approved | ✅ | no |
| youtube | approved | ✅ | no |
| x | manual discovery only | ❌ | yes (not configured) |
| reddit | manual discovery only | ❌ | yes (not configured) |
| linkedin | manual discovery only (public-page) | ❌ | yes (not configured) |
| instagram | deferred | ❌ | yes (not configured) |
| facebook | deferred | ❌ | yes (not configured) |
| tiktok | deferred | ❌ | not supported |
| bilibili | deferred | ❌ | no |
| xiaohongshu | deferred | ❌ | yes (not configured) |
| v2ex | deferred | ❌ | no |
| xiaoyuzhou (podcast) | deferred | ❌ | no |
| xueqiu | deferred | ❌ | yes (not configured) |
| search (Exa) | deferred | ❌ | no |
