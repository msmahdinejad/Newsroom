# Final Architecture

## Purpose

Newsroom is a single-host, PostgreSQL-backed Persian technology newsroom. It
collects reviewed public sources, preserves audit and cursor state, groups
related evidence, produces grounded Persian reports through a bounded
multi-provider LLM router, and delivers reports through Telegram.

## Runtime topology

```text
reviewed workbook
      |
      v
source inventory -----> source registry / health / cursors
      |                              |
      v                              v
native HTTP collectors     Telegram MTProto / X / Agent-Reach
      \___________________________  __________________________/
                                  \/
                            raw_items (immutable identity)
                                  |
                                  v
                  normalize -> deduplicate -> cluster
                                  |
                                  v
                      stories -> evidence lineage
                                  |
                                  v
               bounded map jobs -> accepted artifacts
                                  |
                                  v
             validated reduction -> report -> Telegram chunks
                                  |
                                  v
               delivery cursor advances only when complete
```

Docker Compose owns eight services:

- `postgres`: durable PostgreSQL 16 storage.
- `migrate`: one-shot Alembic upgrade before application services start.
- `collector`: bounded native RSS/Atom, web/newsletter, Reddit, GitHub, and
  YouTube collection.
- `telegram-ingestor`: the only MTProto session owner.
- `agent-reach-worker`: the pinned Agent-Reach capability process and X
  timeline owner.
- `report-worker`: scheduled/manual processing and editorial work.
- `scheduler`: the only production schedule owner.
- `telegram-bot`: the only Telegram Bot API polling owner.

The scheduler uses `Asia/Tehran` and owns the 00:00, 06:00, 12:00, and 18:00
report jobs. PostgreSQL advisory locks prevent overlapping pipeline work.

## Module boundaries

| Boundary | Primary package | Durable state |
|---|---|---|
| Registry and import | `newsroom.sources.inventory` | `source_inventory`, `sources` |
| Collection | `newsroom.sources`, `newsroom.pipeline.collect` | `raw_items`, platform cursors, source attempts |
| Processing | `newsroom.processing` | normalized items, stories, clusters |
| Evidence | `newsroom.editorial.evidence` | evidence and lineage rows |
| Editorial jobs | `newsroom.editorial.hierarchy` | jobs, shards, artifacts |
| LLM routing | `newsroom.editorial.router` | safe key/model/provider metadata and attempts |
| Scheduling | `newsroom.scheduler` | APScheduler jobs and job runs |
| Delivery | `newsroom.delivery` | reports, deliveries, chunks, message IDs |
| Operations | `newsroom.cli` and `scripts/` | read-only health/status output |

Collectors isolate failures per source. They use stable external identities,
bounded fetch sizes, durable cursors, and database uniqueness constraints.
Disabling a source changes scheduling state; it does not delete prior evidence.

## LLM router

Provider order is Gemini, Mistral, Groq, NVIDIA, then deterministic editorial
fallback. Only models that pass live connectivity, Persian, schema, parsing,
grounding-compatibility, and bounded-output checks can be enabled.

Each map or reduction call enters a bounded shared queue. Admission accounts
for estimated input tokens; completion reconciles actual usage. Provider and
model semaphores, rate budgets, minimum spacing, access-value cooldowns, and
provider circuit breakers prevent request bursts. Safe one-way access-value
fingerprints allow restart recovery without persisting the original value.

Artifact identity is independent of provider selection. A route switch retries
only the failed stage and reuses accepted artifacts. The final report records
the actual provider/model lineage; provider failure cannot create another
report or another Telegram delivery.

## Data integrity and idempotency

Important constraints and keys include:

- stable workbook ID and stable source identity;
- platform-specific external item ID;
- normalized content and URL identity;
- editorial job, shard, artifact, and evidence lineage identity;
- report/window identity;
- `(report_id, chat_id fingerprint)` delivery identity;
- `(delivery_id, chunk_index)` Telegram chunk identity;
- Telegram `update_id`;
- fingerprint-only manual command request identity.

Scheduled delivery state advances only after every Telegram chunk has a real
message ID and the delivery is complete. Partial retries send only missing
chunks. No-news windows make no provider request.

## Security and trust boundaries

Source material is untrusted and may contain prompt injection. Prompts delimit
evidence, structured schemas constrain responses, and grounding validation
rejects unsupported output.

Runtime access is isolated by file and service:

- `.env`: application, Telegram, database, and proxy configuration;
- `.env.providers.local`: editorial provider access and routes;
- `.env.x.local`: X access state;
- the `telegram_sessions` volume: MTProto authorization;
- the Agent-Reach data volume: isolated external-tool state.

These local files and volumes are excluded from Git and the Docker build
context. Access values are neither logged nor stored in PostgreSQL. Durable
Telegram bot audit rows contain one-way identity fingerprints, not raw owner
or chat identifiers.

## Recovery model

PostgreSQL and named volumes survive service and host restarts. Workers reload
source cursors, validation/cooldown state, accepted artifacts, scheduler jobs,
delivery chunks, and message IDs. Provider circuits enter half-open through a
single bounded probe after cooldown. Collector errors remain source-local.

This design intentionally targets a reliable single-host deployment. It does
not claim unlimited provider quota, unrestricted social-platform access, or
horizontal multi-region scheduling.
