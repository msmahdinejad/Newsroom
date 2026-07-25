# Gate 7 Source and Collector Audit

## Scope and method

This audit independently rechecked the source inventory and every production
collector boundary. It did not trust Gate 1-6 reports as proof. Evidence came
from deterministic tests, a real PostgreSQL database, the running Docker
services, bounded live public reads, and safe aggregate status output. No
session, cookie, token, proxy endpoint, proxy credential, source content, or
private workbook path is included here.

## Requirements ledger

| Requirement | Initial | Initial evidence | Corrective action | Final evidence | Final |
|---|---|---|---|---|---|
| Authoritative workbook is portable | FAIL | discovery depended on an owner-specific OneDrive directory; the canonical copied filename was not rediscoverable | added `--workbook`, `NEWSROOM_SOURCE_WORKBOOK`, repo-local discovery, idempotent canonical copy, and filename-only output | 7 portability tests pass | PASS |
| 1344 rows reconcile | PASS | real `All Sources!A1:T1345` import: 1344 rows and 1344 distinct workbook IDs | none | two repeated imports retained 1344 rows; zero missing, extra, metadata, or stable-identity mismatches | PASS |
| Native HTTP client lifecycle is bounded | FAIL | a production cycle leaked the HTML, Reddit, and YouTube clients | close all six collector instances in `finally` | lifecycle regression test passes | PASS |
| Native production batch is bounded and fair | FAIL | the Compose loop admitted the entire stateless registry and a first capped pass selected 20 Reddit sources, concentrating rate-limit pressure | cap each cycle at configurable 20 sources, select the least-recent attempt once per source type per round, and space request starts by a configurable one second | two production cycles each attempted exactly 20 distinct sources: four each for GitHub, Reddit, RSS, web, and YouTube | PASS |
| Website/newsletter SSRF boundary | FAIL | HTTPX followed redirects before a private-address check | disabled automatic redirects and validate every target before the next request; maximum 5 redirects | private redirect is rejected after one public request | PASS |
| Stable web item identity | FAIL | a page with a self-link emitted the source URL twice; live read returned 26 identities but only 25 unique | reserve the page-level URL before processing anchors | deterministic self-link regression passes | PASS |
| Safe native failure state | PARTIAL | raw exception text was stored and failures could remain `healthy`; category was only `CollectionError` | redact details before persistence, reduce to safe category, and mark the source degraded immediately | rate-limit isolation/redaction regression passes | PASS |
| Native cross-worker dedup | FAIL | one historical RSS duplicate pair was inserted 1.3 ms apart by a check-then-insert race | added a PostgreSQL transaction-scoped advisory lock per source to native and Agent-Reach persistence | real PostgreSQL contention test passes; Telegram/X duplicate identity groups remain zero | PASS |
| Native proxy routing | FAIL | Reddit DNS was unavailable on the host and in the collector while the host SOCKS route was reachable | added isolated `COLLECTION_PROXY_URL` support for HTTP/HTTPS/SOCKS5, `socksio`, and a shared safe HTTP client builder | proxy configuration appears only in the collector service; deterministic proxy tests pass | PASS |
| Telegram permanent identity failures | FAIL | 8 conclusively unresolvable sources remained enabled and could be retried forever | permanent channel failures now deactivate source and inventory; startup reconciliation repairs prior rows; later imports preserve the reason | permanent-failure regression passes | PASS |
| Telegram MTProto owner/session isolation | PASS | dedicated healthy service, protected session path, SOCKS5 transport, session volume absent from other services | preserved | safe health: authenticated and connected; 149 configured/healthy channels | PASS |
| X worker isolation and continuation | PASS | isolated worker receives only X auth state and DB access; 139 active sources have cursors | preserved | latest safe cycle: 12 attempted, 0 failed; zero duplicate X post groups | PASS |
| Agent-Reach revision and doctor | PARTIAL | package/revision were pinned, but POSIX timeout cleanup could signal the worker process group and output was truncated only after buffering | start every POSIX child in a new session; drain stdout/stderr concurrently with a hard retained-byte bound and terminate on overflow | revision `1494c2ab239e7355a77e7cceaf3271453a1f34b5`; v1.5.0 doctor exit 0; real 10 MB output test retains at most 1024 bytes | PASS |
| Agent-Reach SSRF classification | FAIL | `SSRFError` is a `CollectionError`, so the later dedicated handler was unreachable | moved the SSRF handler before the generic handler and persist only category `ssrf` | dedicated path regression passes | PASS |
| Failure isolation | PASS | Telegram, X/Agent-Reach, and native loops catch per-source failures | preserved and added executable native isolation test | one failed source does not stop the next source | PASS |

## Workbook and source-state reconciliation

- Authoritative rows: **1344**
- Distinct workbook IDs: **1344**
- Inventory rows in PostgreSQL: **1344**
- Metadata/stable-identity mismatches: **0**
- Repeated-import row growth: **0**
- Stable-identity duplicate workbook rows retained and classified: **4**
- Inventory states before final runtime reconciliation:
  - active: **1236**
  - inactive: **104**
  - duplicate: **4**
- Inactive rows without a reason: **0**
- Active rows without `last_attempt_at`: **0**
- Healthy rows without an attempt: **0**
- Active invalid links: **0**

Authoritative platform totals are Telegram 159, Reddit 204, Community 45,
X/Twitter 144, Website/Newsletter 464, GitHub 246, Community/Forum 19, and
YouTube/Social 63.

The collector registry also intentionally contains 34 enabled non-workbook
sources: 22 RSS, 11 GitHub release sources, and one legacy X timeline. They
remain separately identifiable because `workbook_id` is null.

## Live collection evidence

| Platform | Bounded live result | Stable identity evidence | Durable state |
|---|---|---|---|
| RSS/Atom | 20 items | 20/20 unique entry IDs/links | 22 active sources have cursors |
| GitHub releases | 1 release | 1/1 unique release ID | cursor and content-hash dedup enabled |
| Website/newsletter/forum/community | 26 pre-fix items exposed one self-link duplicate; regression fixed | final code reserves the page URL and caps links/redirects | 443 active sources have cursors |
| YouTube | 15 videos | 15/15 unique video IDs | 57 active sources have cursors |
| Reddit | host/container DNS initially failed while SOCKS route was reachable | shared proxy route added; final live result recorded below | cursor uses bounded post IDs |
| X | production worker cycle attempted 12 and failed 0 | zero duplicate post-ID groups | 139 active sources have cursors |
| Telegram | production service connected and authenticated through SOCKS5 | zero duplicate channel/message-ID groups | 149 channel cursors; 8 permanent unresolvable rows are classified and will be deactivated by the new startup reconciliation when the ingestor image is recreated |

### Final proxy-backed Reddit result

The rebuilt collector selected the safe `socks5_proxy` transport without
emitting its endpoint. A bounded live read returned **25 posts**, all **25**
with stable post IDs and **25 unique** IDs. The first fair production cycle
then attempted four Reddit sources: one succeeded and three returned isolated
safe `rate_limit` failures. The other 16 platform attempts all succeeded.

The durable Reddit cursor population advanced from **52 to 53**. After a
collector restart, the next fair cycle again attempted exactly four sources
from each of the five stateless platforms; the same one-success/three-429
Reddit result did not stop the other platforms. All **53** Reddit cursors
survived the restart. Duplicate Reddit post-ID groups remained **0**.

## Runtime isolation

Expanded Compose configuration shows:

- `collector`: database, bounded collection controls, and the optional
  collector proxy only.
- `telegram-ingestor`: database, MTProto identity/session configuration, and
  Telegram transport controls; no bot token, X access, or LLM provider file.
- `agent-reach-worker`: database, isolated Agent-Reach config, bounded worker
  controls, and X-only local access; no Telegram session volume or provider
  file.
- `telegram-bot`: no MTProto session volume.
- `COLLECTION_PROXY_URL` appears in exactly one service: `collector`.

The source workbook path is not emitted. The import report contains only the
workbook filename. Proxy protocol labels never include endpoints or
credentials. Final scans found zero protected route matches in tracked files,
collector logs, and PostgreSQL data.

## Retry, rate, and restart properties

- Every source attempt has its own `collection_runs` row.
- Failure handling is per source; a failure does not abort the remaining
  batch.
- Telegram FloodWait state and X rate-limit categories are durable.
- HTTP clients have bounded connection pools and timeouts.
- Native fetches have response-size checks and per-cycle item caps.
- The production stateless loop admits at most 20 sources per cycle by
  default, round-robins source types by oldest attempt, and spaces request
  starts by one second; all controls are environment-overridable.
- Telegram and X use least-recently-attempted bounded batches.
- Native and Agent-Reach check/dedup/insert/cursor operations are serialized
  per source across workers by a PostgreSQL advisory transaction lock.
- Cursors advance only after persistence flush succeeds.
- HTTP clients and MTProto clients close at the cycle boundary.
- Agent-Reach subprocesses use `shell=False`, sanitized environments,
  timeouts, isolated POSIX process groups, retained-output bounds, and
  overflow termination.

## Verification commands

```text
uv run pytest -q tests/test_telegram_deterministic.py tests/test_telegram_persistence.py tests/test_x_timeline.py tests/test_connector_production_runtime.py tests/test_agent_reach.py tests/test_native_adapters.py tests/test_sources.py tests/test_collector_lifecycle.py tests/test_source_workbook_portability.py tests/test_http_collector_proxy.py tests/test_source_collection_lock.py tests/integration/test_gate7_source_lock.py
uv run ruff check src tests
uv run mypy src/newsroom
docker compose config --quiet
docker compose build collector
```

## Preserved historical evidence

One historical RSS raw-item duplicate group remains in PostgreSQL because raw
evidence is append-only and must not be deleted during an audit. Its two rows
were inserted 1.3 ms apart. The new cross-worker lock prevents recurrence;
two rebuilt production cycles plus a collector restart left the duplicate
group count unchanged at **1**. Duplicate Reddit post-ID and Telegram
channel/message-ID groups remained **0**.
