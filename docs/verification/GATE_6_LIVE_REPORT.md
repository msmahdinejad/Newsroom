# Gate 6 — Live Report Verification

## Live AI report (non-fallback)

A real scheduled-style report completed with `generation_method=ai`,
produced by the configured OpenAI-compatible provider — **no fallback**.

| Field | Value |
|---|---|
| Report ID | 368 |
| Report mode | `scheduled` |
| Generation method | `ai` |
| Editorial provider | `openai_compatible` |
| Editorial model | `gemini-3.1-flash-lite` |
| Editorial status | `ok` |
| `fallback_used` | `False` |
| Hierarchical | `True` (shard_count=2) |
| Total model calls | 3 |
| Total input tokens | 29471 |
| Total output tokens | 2223 |
| Fallback shards | 0 |
| Stories selected | 30 (of 100 candidates) |
| Delivery ID | 337 |
| Delivery status | `delivered` |
| Telegram message IDs | `[43]` (1 chunk) |
| Scheduled cursor advanced to | report 368, delivery 337 |

## Pipeline stages (measured)

- collect: skipped (NEWSROOM_SKIP_COLLECT for the on-existing-items run)
- normalize: 500 items
- dedupe: 74 duplicates marked (9 url_match, 65 near_dup) — cross-source dedup ✓
- cluster: 326 stories created, 426 items clustered — cross-source clustering ✓
- evidence: 30 packets built
- report: hierarchical editorial, 2 shards, 3 model calls, **0 fallback**
- deliver: 1 chunk via Bot API (HTTP 200), cursor advanced after complete delivery

## Telegram delivery & message IDs (persisted)

- Delivery 337: `delivered`, `message_ids=[43]`, `delivered_at` set.
- The Telegram message ID **43** is persisted in `deliveries.message_ids`
  and `delivery_chunks.telegram_message_id`.
- The scheduled cursor `scheduled_delivery` advanced to (report 368,
  delivery 337) **only after** `delivery.status='delivered'`.

## Second window

- Report 369 (`generation_method=ai`) — additional new material from
  leftover un-normalized items; delivery 338, message_id `[44]`, cursor
  advanced to 369.

## No-news path (verified live)

- Report 370 (`generation_method=none`, `story_ids=[]`) — zero editorial
  provider calls (`editorial_attempts` total unchanged at 2; 0 attempts for
  report 370).
- One short Persian no-news notice delivered via Telegram (delivery 339,
  `message_ids=[45]`).
- Cursor advanced to (370, 339); no unrelated stories marked delivered.

## Editorial & grounding requirements (kept)

- Evidence lineage: `editorial_artifact_lineage` traces final → reduction →
  map → story → evidence_ref → source_url.
- Source attribution: every rendered story links original source URLs.
- Grounding validation: claims grounded against evidence (AI providers);
  fallback to deterministic only on provider failure (not used here).
- Hierarchical sharding: bounded shards with stable shard IDs.
- Cross-platform deduplication: content_hash + url_hash dedup.
- Persian rendering: `_render_persian_report` (headline/summary/why/impact,
  ریزخبرها for low-priority items).
- Provider usage records: `editorial_attempts.usage` (token counts),
  `editorial_jobs`/`editorial_shards` token/call budgets.
