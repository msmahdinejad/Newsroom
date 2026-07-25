# Gate 7 Live Results

All figures below are aggregate operational evidence. They contain no source
credentials, owner identifiers, proxy endpoints, session paths, or provider
access values.

## Source inventory

- Authoritative workbook: 1344 rows represented exactly; zero missing and zero
  unexpected workbook IDs after repeated import.
- Final states: 1228 active, 112 inactive with explicit reasons, 4 retained
  duplicate rows.
- 1329 workbook-linked rows have persisted attempts; every active row (1228)
  has an attempt and either a cursor or explicit no-cursor reason.
- Linked active health: 965 healthy and 263 degraded. Degraded is a retryable
  operational state, not an unattempted or silently accepted source.

## Bounded platform collection

| Platform | Live/restart evidence | Durable result |
| --- | --- | --- |
| Telegram | Authenticated MTProto over SOCKS5; post persisted after restart | 149 active channels and cursors; zero duplicate channel/message IDs |
| X | Pinned Agent-Reach worker performed bounded authenticated timeline reads | 144 workbook rows attempted; 138 active/cursored; zero duplicate post IDs |
| RSS/Atom | Native bounded feeds collected | Stable entry/link IDs and durable cursors |
| Websites/newsletters/community | Bounded native reader collected public items; isolated failures continued | URL/content dedup and per-source runs |
| GitHub | Native release/repository reads collected | Stable release IDs and cursors |
| YouTube | Native RSS reads collected | Stable video IDs and cursors |
| Reddit | Proxy-backed bounded public reads collected 25/25 unique posts | Cursor survived collector restart; rate limits isolated |
| Agent-Reach | Doctor and bounded read completed at pinned revision | Controlled output bound and durable backend state |

Source-specific rate, access, and malformed-source failures are recorded with
safe categories. They do not abort other sources in a cycle.

## Editorial and delivery

The final scheduled-style run used a capped native collection pass (20 sources
per collector pass, Telegram/X owned by dedicated workers), generated report
502 through the validated hierarchical AI route, and completed delivery 465
with message ID 76. The scheduled cursor points to that delivered report.
