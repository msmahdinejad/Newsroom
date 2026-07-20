# Gate 5X — X/Twitter Production Ingestion Architecture

**Date:** 2026-07-20
**Pinned Agent-Reach revision:** `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (v1.5.0)
**Selected backend:** twitter-cli v0.8.5 (Apache-2.0)
**Production approval:** `approved with dedicated authentication` (pending live verification)

## 1. Overview

Gate 5X upgrades X/Twitter from `manual discovery only` (Gate 5) to production ingestion for a reviewed allowlist of accounts. It uses:

- the pinned Agent-Reach revision already recorded in Gate 5
- its audited `twitter-cli` backend (v0.8.5, Apache-2.0)
- the existing `ControlledRunner` with `shell=False`
- isolated Agent-Reach config for authentication

The owner accepts X account restriction risk. Credential leakage and unreliable unattended operation remain blockers.

## 2. Controlled command boundary

The `twitter` executable is added to the `ControlledRunner`'s `EXECUTABLE_ALLOWLIST` with four read-only operations:

| Operation | Purpose | Auth required |
|---|---|---|
| `status` | auth check (capability probe) | no tokens passed |
| `user` | resolve handle to stable numeric account ID | yes |
| `user-posts` | bounded account timeline read | yes |
| `tweet` | single-post reconciliation by stable post ID | yes |

All operations emit JSON (`--json` flag). The adapter validates the handle/post-id before calling; the runner enforces the operation allowlist and `shell=False`.

**Forbidden operations** (not in the allowlist, rejected by the runner):
- `search`, `post`, `reply`, `like`, `unlike`, `retweet`, `unretweet`, `follow`, `unfollow`, `bookmark`, `unbookmark`, `delete`, `quote`, `favorite`, `unfavorite`

## 3. Authentication boundary

- `TWITTER_AUTH_TOKEN` and `TWITTER_CT0` are read from the host environment (named by `source.config['auth_token_env']` and `source.config['ct0_env']`).
- They are passed via `extra_env` to the controlled runner ONLY for `user`, `user-posts`, and `tweet` operations.
- They NEVER enter the database, repo, logs, health output, or the default sanitized environment.
- The `twitter:status` operation is called WITHOUT tokens (capability probe).
- If the env vars are not set, the adapter raises `CollectionError(auth_not_configured)` — it never silently proceeds.
- The owner must use a dedicated operational X account, never the primary account.

## 4. Production behavior

Supported:
- resolve configured account (handle → stable numeric account ID)
- bounded recent account timeline (`user-posts -n N`)
- bounded single-post reconciliation (`tweet TWEET_ID`)
- quote-post metadata (`quotedTweet` field)

Not supported (forbidden by the operation allowlist):
- production search
- posting, replies, likes, follows, DMs, account changes

## 5. Identity and persistence

**Identity:** `x + post_id` — stable numeric post ID, never display name or text.

**Persisted per item (raw_data):**
- stable numeric account ID (`account_id`)
- handle (`handle`)
- stable post ID (`post_id`)
- canonical URL (`canonical_url`)
- timestamp (`published`)
- bounded text (`text`, max 2000 chars)
- reply/repost/quote relationships (`post_kind`, `is_retweet`, `retweeted_by`, `quoted_tweet`)
- media metadata (`media`, bounded to 4 items)
- content hash (`content_hash = sha256("x:{post_id}")`)

**Persisted per account (x_account_state table):**
- stable numeric account ID (`account_id`)
- configured handle (`configured_handle`)
- last resolved handle (`last_resolved_handle` — may differ on rename)
- per-account cursor (`cursor` — bounded `seen_item_ids` set, last 200)
- health status (`health_status`)
- rate-limit state (`rate_limit_state`, `retry_after`)
- error category (`last_error_category` — safe diagnosis, never raw output)
- counts (`consecutive_failures`, `total_posts_collected`)

**Not persisted (anywhere):**
- cookies
- auth tokens
- authorization headers
- browser profile paths
- Agent-Reach config contents

## 6. Bounded defaults

| Parameter | Default |
|---|---|
| poll interval | 30 minutes |
| max posts per account per poll | 20 |
| initial backfill | 30 |
| overlap | 5–10 (we use 8) |
| concurrency | 1 (one account at a time) |
| timeout | `AGENT_REACH_TIMEOUT_SECONDS` (60s default) |
| retries | `AGENT_REACH_MAX_RETRIES` (1 default) |
| text bound | 2000 chars |
| media bound | 4 items |
| seen_item_ids bound | last 200 |

## 7. Inclusion policy

| Post kind | Default | Configurable |
|---|---|---|
| original | include | always |
| quote | include (with quoted_tweet metadata) | always |
| reply | exclude | `source.config['include_replies'] = true` |
| repost | exclude | `source.config['include_reposts'] = true` |

## 8. Reliability

- PostgreSQL-backed per-account cursor (`x_account_state.cursor`)
- restart continuation (cursor loaded from DB on restart; `filter_new_items` drops seen posts)
- duplicate prevention (raw_items `content_hash` dedup)
- account-specific failure isolation (one failing account does not block others)
- rate-limit/challenge backoff (`_classify_failure` → `rate_limit` / `challenge` / `auth_failure` / `timeout` / `not_found` / `transient`)
- changed content updates the existing post (same `post_id` → same `content_hash` → in-place update)
- temporary failure is NOT treated as deletion (failed posts are not removed; `health_status` degrades)
- collected text remains untrusted data (prompt-injection isolation enforced; text never reaches the runner as a command argument)

## 9. Pipeline flow

```
X timeline source (type=x_timeline)
  → XTimelineCollector.collect(source)
    → resolve account (cached or twitter user --json)
    → twitter user-posts -n N --json (via ControlledRunner, extra_env=auth)
    → parse JSON array → classify post_kind → filter by inclusion policy
    → list of raw item dicts (type=x_post)
  → gate5_collect pipeline
    → cursor filter (drop seen_item_ids)
    → raw_items persist (content_hash dedup)
    → cursor advance (seen_item_ids + last_stable_item_id)
    → x_account_state upsert (account_id, health, cursor)
  → normalize (x + post_id identity)
  → cluster → story → evidence → AI editorial → Telegram delivery
```

## 10. Capability registry

`apply_default_production_decisions()` keeps X at `MANUAL_DISCOVERY` by default. `upgrade_x_to_production(registry)` flips X to `APPROVED_WITH_AUTH` and marks it `production_ready` — called only after live verification confirms:
1. local X auth is configured
2. a reviewed curated account list exists
3. bounded real-read verification of timeline monitoring succeeded
4. restart and cursor continuation work
5. three polling cycles operated unattended across restart

## 11. Live verification status

**BLOCKED** — pending owner configuration of local X auth (`TWITTER_AUTH_TOKEN` + `TWITTER_CT0` env vars from a dedicated operational account) and a reviewed curated account list (5–30 public X handles).

Non-live tests (55 deterministic + 15 integration) all pass. The live verification procedure is defined in `scripts/gate5x_live_verification.py` (to be run after auth + accounts are supplied).

## 12. Files added/modified

| File | Change |
|---|---|
| `src/newsroom/sources/agent_reach/runner.py` | add `twitter` executable + 4 operations to allowlist; add `validate_x_handle`, `validate_x_post_id`; add `extra_env` to `run_upstream` |
| `src/newsroom/sources/agent_reach/adapters.py` | add `XTimelineCollector`; add `upgrade_x_to_production` |
| `src/newsroom/sources/agent_reach/__init__.py` | export new symbols |
| `src/newsroom/processing/normalize.py` | update `_normalize_x_post` for timeline fields |
| `src/newsroom/pipeline/gate5_collect.py` | add `x_timeline` to source types + adapter mapping |
| `src/newsroom/pipeline/cursors.py` | add `x_timeline` to cursor handling |
| `src/newsroom/storage/models.py` | add `XAccountState` model |
| `src/newsroom/storage/migrations/versions/0008_gate5x_x_ingestion.py` | new migration |
| `tests/test_x_timeline.py` | 55 deterministic tests |
| `tests/integration/test_gate5x_x_ingestion.py` | 15 integration tests |
