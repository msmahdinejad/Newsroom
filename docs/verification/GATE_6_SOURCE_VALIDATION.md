# Gate 6 — Source Validation & Activation Verification

## Activation result (total 1344)

| State | Count |
|---|---|
| active | 1185 |
| inactive | 155 |
| invalid | 0 |
| duplicate | 4 |

## Per-platform operational state

| Platform | active | inactive | duplicate | invalid |
|---|---|---|---|---|
| Telegram | 157 | 0 | 2 | 0 |
| Reddit | 204 | 0 | 0 | 0 |
| Community | 36 | 9 (access_required) | 0 | 0 |
| Community / Forum | 19 | 0 | 0 | 0 |
| X / Twitter | 0 | 144 (x_auth_not_configured) | 0 | 0 |
| Website / Newsletter | 462 | 0 | 2 | 0 |
| GitHub | 244 | 2 (not_a_repo) | 0 | 0 |
| YouTube / Social | 63 | 0 | 0 | 0 |

## Inactive sources and summarized reasons (evidence-based)

| Reason | Count | Explanation |
|---|---|---|
| `x_auth_not_configured` | 144 | X/Twitter timeline ingestion requires owner-side auth (`TWITTER_AUTH_TOKEN` + `TWITTER_CT0`); not set in this environment. Sources remain registered; not attempted. |
| `access_required` | 9 | Discord/Slack/Bot communities need membership/owner-side access. Only documented public endpoints are used; no alternate access attempted. |
| `duplicate_identity` | 4 | Same source appears on multiple workbook rows; first occurrence retained, duplicates marked (no silent disappearance). |
| `not_a_repo` | 2 | GitHub URLs that are not `owner/repo` (e.g. `github.com/trending`) — no release feed to poll. |

All inactive rows carry a concise `inactive_reason` using the repository's
existing state vocabulary. No source is silently dropped.

## Validation waves (progressive activation)

1. **Wave 1** — one representative source per supported platform:
   `scripts/gate6_live_verification.py` (RSS, GitHub, Reddit, web_page,
   YouTube, Telegram).
2. **Wave 2** — reviewed Core sources.
3. **Wave 3** — discovery + community sources.
4. **Wave 4** — remaining valid review-tier sources.

Every enabled source receives at least one bounded collection attempt
(`limit_per_source=10`). A failed source is recorded per-source
(`last_error`, `consecutive_failures`, `health_status=degraded` after 3
failures) and does **not** interrupt other collectors or scheduled reports.

## Per-source persisted state

For every source: stable identity, validation state, `last_success_at`,
`last_error_at`, durable cursor (`collection_cursors`), collected-item count
(via `raw_items`), safe error category, retry time, and health state
(`configured`/`healthy`/`degraded`/`unavailable`).

## Platform collection results (live, measured)

| Platform | Collector | Live result |
|---|---|---|
| RSS | native RSSCollector | ✓ 20 items fetched (AI Snake Oil), 30 releases (HelloGitHub) |
| GitHub releases | native GitHubCollector | ✓ 30 releases fetched |
| Reddit | native RedditSubredditCollector (.rss) | ✓ 10 new posts (r/3Dprinting) |
| Website / Newsletter | native HtmlReader | ✓ 10 new links (01net) |
| YouTube / Social | native YouTubeRssCollector | ✓ 10 new videos (3Blue1Brown) |
| Telegram (MTProto) | native TelegramMTProtoCollector | ✗ connection refused at network level (DC 149.154.175.60) — recorded degraded, not a code failure |
