# Architecture

Newsroom is a modular monolith deployed as bounded worker processes. PostgreSQL
is the durable coordination seam; every worker can restart without losing
cursor, report, quota, or delivery state.

## Data flow

```text
source registry
      |
      v
bounded collectors -> raw items + cursors + source health
      |
      v
normalize -> deduplicate -> cluster -> rank -> evidence
                                                |
                                                v
                                queued multi-provider router
                                                |
                                                v
                                  localized report + lineage
                                                |
                                                v
                                   idempotent Telegram delivery
```

## Modules and interfaces

- `control` owns operator preferences and source lifecycle. Callers do not
  know CSV/XLSX details or source-state invariants.
- `sources` owns external collection adapters, request bounds, cursor formats,
  and safe failure categories.
- `processing` turns untrusted collected data into deterministic stories and
  evidence.
- `editorial` owns provider routing, structured output, grounding, artifact
  reuse, and deterministic fallback.
- `delivery` owns authorization, localization, chunking, Telegram retries, and
  delivery idempotency.
- `pipeline` coordinates the modules and owns transaction boundaries.
- `storage` owns PostgreSQL models, repositories, and migrations.

External providers are true external dependencies. Production adapters perform
network I/O; deterministic fakes exercise the same interfaces in tests.

## Persistence invariants

- A source has a stable identity independent of its display name.
- A collected item is unique within its source identity.
- Cursor advancement and item persistence share a transaction boundary.
- An editorial artifact records the provider and model that produced it.
- Provider changes reuse accepted artifacts and retry only the failed stage.
- A report is delivered at most once per idempotency boundary.
- Scheduled delivery advances only after every Telegram chunk is persisted.
- Credentials, cookies, sessions, and proxy access values are never stored in
  PostgreSQL.

## Process ownership

| Process | Responsibility |
| --- | --- |
| `collector` | Native public collectors and processing loop |
| `telegram-ingestor` | Telethon MTProto channel ingestion |
| `agent-reach-worker` | Isolated authenticated social collection |
| `report-worker` | Background processing |
| `scheduler` | Tehran cron jobs and scheduled pipeline ownership |
| `telegram-bot` | Owner commands and manual report requests |
| `migrate` | One-shot schema migration before dependent workers start |

All application containers run without root privileges. The social worker does
not receive Telegram sessions or editorial provider files. Provider files are
mounted read-only only into processes that generate reports.
