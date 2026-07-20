# Gate 5 — X / Twitter Decision

**Decision date:** 2026-07-18
**Pinned Agent-Reach revision:** `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (v1.5.0)
**Production approval:** `manual discovery only`

## 1. Doctor output

```
twitter: status=off, active_backend=null, tier=1, backends=[twitter-cli, OpenCLI, bird]
```

All listed backends require cookies or OpenCLI authentication. None are configured.

## 2. Distinguishing read scenarios

Per gate spec section 7, we distinguish:

| Scenario | Requires auth | Production-suitable in Gate 5? |
|---|---|---|
| Reading one public tweet URL | no (via Jina Reader) | yes (manual) |
| Monitoring a curated account | yes (cookies) | no |
| Searching posts | yes | no |
| Reading timelines | yes | no |

## 3. Newsroom adapter

`XPublicReadCollector` (`src/newsroom/sources/agent_reach/adapters.py`)

- Reads a single public X/Twitter post URL via Jina Reader.
- No persistent authentication.
- No cookies.
- No timeline monitoring.
- URL must contain a `/status/` segment (profile URLs are rejected).
- Post ID is extracted from the URL — never from page content.
- Content is bounded to 8000 chars.

## 4. Production integration requirements (NOT met in Gate 5)

Per gate spec section 7, production integration is allowed only when:

1. ✗ The selected Agent-Reach backend passes real bounded tests — no backend configured.
2. ✗ An explicit curated account list exists — none defined.
3. ✗ Durable cursors can be implemented — not implemented (no monitoring).
4. ✗ Stable post IDs are returned — the adapter extracts them from URLs, but no monitoring means no cursor.
5. ✗ Unattended operation is reliable — not tested.
6. ✗ Platform access is acceptable to the owner — not confirmed.
7. ✗ Any required authentication is locally configured — none configured.
8. ✗ A dedicated non-primary account is used when cookies are required — no cookies configured.

## 5. Security constraints (enforced regardless of approval)

- No cookies requested in Qwen chat.
- No cookies printed.
- No cookies stored in PostgreSQL.
- No host primary browser profile mounted into Docker.
- No cookies passed through the controlled runner environment.

## 6. Decision

**`manual discovery only`** — a human may use the `XPublicReadCollector` to read a single public post URL for one-off research. Unattended production ingestion is deferred until the requirements above are met.

Default classification: `available for manual discovery, deferred for unattended production ingestion`.

## 7. Path to production (future gate)

1. Owner explicitly approves platform access.
2. Owner creates a dedicated non-primary X account.
3. Cookies are configured locally in the isolated `agent_reach_config` directory (never in the database, never in the repo).
4. `AGENT_REACH_ALLOW_AUTHENTICATED_CHANNELS=true` is set by the owner.
5. An explicit curated account list is defined in `config/sources.production.example.yaml`.
6. A bounded real-read test of account monitoring succeeds.
7. The capability registry flips `x` to `production ingestion approved with dedicated authentication`.
