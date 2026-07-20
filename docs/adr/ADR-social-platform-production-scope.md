# ADR: Social-Platform Production Scope

**Status:** accepted
**Date:** 2026-07-18
**Pinned Agent-Reach revision:** `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (v1.5.0)

## Context

The Persian AI Newsroom must decide which social and external content channels are genuinely useful for unattended production ingestion. Agent-Reach supports 18 channels, but supporting a channel in production has real costs:

- authentication complexity (cookies, browser sessions, dedicated accounts)
- operational risk (rate limits, ToS, account suspension)
- security exposure (credentials in containers, browser-profile mounts)
- editorial relevance to a Persian AI and technology newsroom

Supporting a channel merely because Agent-Reach supports it is not sufficient.

## Decision

Apply a tiered production-scope decision to every evaluated channel:

- `production ingestion approved` — unauthenticated, bounded, allowlisted, verified by a real read.
- `production ingestion approved with dedicated authentication` — owner opt-in, dedicated account, locally configured credentials, bounded real-read verified.
- `manual discovery only` — a human may use the capability for one-off research; no scheduled ingestion.
- `deferred` — capability present but not yet verified or not yet useful.
- `rejected` — unsafe or unsuitable; will not be revisited.

## Approved production scope (Gate 5)

| Channel | Production scope | Rationale |
|---|---|---|
| Telegram (existing) | production ingestion approved | Native MTProto ingestion (Gate 3) — unchanged |
| RSS (existing) | production ingestion approved | Native feedparser collector (Gate 1) — unchanged |
| Websites | production ingestion approved | Allowlisted public-domain reading via Jina Reader with SSRF protection |
| GitHub (existing) | production ingestion approved | Native release collector (Gate 1) — unchanged; Agent-Reach for discovery only |
| YouTube | production ingestion approved | yt-dlp via Agent-Reach; bounded real-read verified; metadata only |
| X (Twitter) | manual discovery only | Public-page reading only; unattended monitoring requires curated accounts + dedicated auth |
| Reddit | manual discovery only | Login required for subreddit monitoring; not configured |
| LinkedIn | manual discovery only (public-page) | Public-page enrichment only; no logged-in automation |
| Instagram | deferred | Browser-session and operational-risk requirements unmet |
| Facebook | deferred | Same as Instagram |
| TikTok | deferred | Not supported by pinned revision |
| Search (Exa) | deferred | Capability present; not bounded-real-read verified |
| Bilibili, V2EX, XiaoYuZhou, XueQiu, XiaoHongShu | deferred | No documented unique-value case for the Persian AI newsroom |

## Authentication policy

- `AGENT_REACH_ALLOW_AUTHENTICATED_CHANNELS` defaults to `false`.
- The owner must explicitly opt in to authenticated channels.
- Dedicated operational accounts must be used — never the owner's primary account.
- Cookies and tokens live only in the isolated `agent_reach_config` Docker volume (file permissions 600), never in the database, never in the repo, never in the image.
- The Telegram MTProto session volume is NEVER mounted into the `agent-reach-worker` container.
- The editorial API key is NEVER passed to the `agent-reach-worker` container.

## Consequences

- The initial production scope is conservative and unauthenticated-safe: Telegram, RSS, websites, GitHub, YouTube.
- Adding X or Reddit to production requires a future gate with explicit owner approval, curated lists, dedicated accounts, and bounded real-read verification of monitoring (not just single-URL reads).
- Adding Instagram, Facebook, or TikTok requires a future pinned Agent-Reach revision with a safe bounded public-read backend, plus owner approval.
- The Newsroom avoids the operational and security costs of authenticated browser-session automation in the initial production scope.
- The decision is recorded per-channel in `agent_reach_backend_state.production_approval` and is visible in the `agent_reach_worker_status()` health output.
