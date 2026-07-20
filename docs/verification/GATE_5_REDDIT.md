# Gate 5 — Reddit Decision

**Decision date:** 2026-07-18
**Pinned Agent-Reach revision:** `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (v1.5.0)
**Production approval:** `manual discovery only`

## 1. Doctor output

```
reddit: status=off, active_backend=null, tier=1, backends=[rdt-cli]
```

The `rdt-cli` backend requires login state. None is configured.

## 2. Newsroom adapter

`RedditPublicReadCollector` (`src/newsroom/sources/agent_reach/adapters.py`)

- Reads a single public Reddit post URL via Jina Reader.
- No login state.
- No subreddit monitoring.
- Post ID is extracted from the URL — never from page content.
- Subreddit is extracted from the URL.
- Content is bounded to 8000 chars.

## 3. Production integration requirements (NOT met in Gate 5)

Per gate spec section 7, production approval requires:

1. ✗ Explicit curated subreddit list — none defined.
2. ✗ Stable authenticated backend — `rdt-cli` not configured.
3. ✗ Dedicated account — none configured.
4. ✗ Durable post and comment IDs — not implemented (no monitoring).
5. ✗ Bounded comment depth — not configured.
6. ✗ Bounded result count — not configured.
7. ✗ Reliable unattended operation — not tested.

## 4. Login requirement

Reddit does not expose a reliable unauthenticated subreddit-monitoring API. The `rdt-cli` backend requires login. Gate 5 does NOT configure login automatically.

## 5. Decision

**`manual research capability only`** — a human may use the `RedditPublicReadCollector` to read a single public Reddit post URL for one-off research. Unattended production ingestion is deferred until the requirements above are met.

## 6. Path to production (future gate)

1. Owner explicitly approves a curated subreddit list.
2. Owner creates a dedicated Reddit account.
3. `rdt-cli` login is configured locally in the isolated `agent_reach_config` directory (never in the database, never in the repo).
4. `AGENT_REACH_ALLOW_AUTHENTICATED_CHANNELS=true` is set by the owner.
5. Bounded comment depth and result count are configured.
6. A bounded real-read test of subreddit monitoring succeeds.
7. The capability registry flips `reddit` to `production ingestion approved with dedicated authentication`.
