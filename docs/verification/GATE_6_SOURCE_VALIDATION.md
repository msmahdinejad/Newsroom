# Gate 6 — Production Source Validation

## Durable source registry snapshot

The bounded production sweep and subsequent scheduled collectors leave no
active source without a durable attempt or cursor accounting.

| Measure | Count |
|---|---:|
| Source rows | 1,371 |
| Sources attempted | 1,369 |
| Active | 1,270 |
| Healthy active | 728 |
| Degraded active | 542 |
| Inactive | 101 |
| Active without attempt | 0 |
| Active without cursor or no-cursor reason | 0 |

The two source rows without an attempt are inactive with explicit reasons. All
1,344 workbook inventory rows are accounted for: 1,236 active, 104 inactive,
and 4 duplicate identities.

| Platform | Total source rows | Active | Healthy | Degraded | Inactive |
|---|---:|---:|---:|---:|---:|
| Unclassified legacy | 42 | 34 | 27 | 7 | 8 |
| Community | 36 | 33 | 33 | 0 | 3 |
| Community / Forum | 19 | 16 | 16 | 0 | 3 |
| GitHub | 244 | 234 | 58 | 176 | 10 |
| Reddit | 204 | 203 | 5 | 198 | 1 |
| Telegram | 157 | 157 | 0 | 157 | 0 |
| Website / Newsletter | 462 | 398 | 394 | 4 | 64 |
| X / Twitter | 144 | 138 | 138 | 0 | 6 |
| YouTube / Social | 63 | 57 | 57 | 0 | 6 |

Transient failures keep an already-approved source degraded and schedulable,
but a source whose first bounded validation only failed is not activated. A
permanent access/identity failure is inactive with a safe category.

## X production restoration

All 144 workbook X accounts were attempted using the ignored `.env.x.local`.
After cooldown recovery and normal worker cycles, 138 are validated, active,
and healthy; 6 remain inactive with explicit upstream-client or inaccessible
categories. No valid tested X source remains marked `x_auth_not_configured`.

The production corpus contains 2,178 X posts, 2,178 distinct post IDs, and
2,178 distinct content hashes. There are 138 durable X cursors and 6 explicit
no-cursor reasons. A fresh-process reread produced zero new rows while
preserving its cursor, and new post reads after the stack restart remained
duplicate-free.

## Telegram

All 157 Telegram sources have bounded attempt records and explicit no-cursor
accounting. They remain degraded because the external network path blocks the
MTProto handshake; the registry does not claim successful Telegram ingestion.
