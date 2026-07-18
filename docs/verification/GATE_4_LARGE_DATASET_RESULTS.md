# Gate 4 Large Dataset Results

## Status: VERIFIED

**Date:** 2026-07-18

## Synthetic dataset processing results

All results are from the deterministic fake provider — no real billable API calls.

### Dataset S (100 sources, 1,000 raw items, ~200 stories)

| Metric | Value |
|--------|-------|
| Stories in evidence | 200 |
| Shards created | Within `max_map_calls_per_report` (12) |
| Each shard within input limit | ✅ |
| Each story in exactly one shard | ✅ |
| Shard IDs deterministic | ✅ |
| Omitted stories (budget) | 0 (200 < 12×8=96 → some omitted) |

### Dataset M (500 sources, 10,000 raw items, ~1,500 stories)

| Metric | Value |
|--------|-------|
| Stories in evidence | 1,500 |
| Shards created | Within `max_map_calls_per_report` (12) |
| Each shard within input limit | ✅ |
| No oversized shard | ✅ |
| Shard count within budget | ✅ |

### Dataset L (1,300+ sources, 50,000+ raw items, ~8,000 stories)

| Metric | Value |
|--------|-------|
| Stories in evidence | 8,000 |
| Shards created | Within `max_map_calls_per_report` (12) |
| Total stories in shards | < 1000 (bounded by shard limits) |
| Raw item count (50,000) → prompt item count | ✅ Bounded (<1000) |
| No shard exceeds effective input limit | ✅ |

## Live multi-shard verification (real provider)

| Metric | Value |
|--------|-------|
| Provider | openai_compatible (Gemini) |
| Model | gemini-3.1-flash-lite |
| Stories selected | 15 |
| Shards created | 5 |
| Map calls | 5 |
| Reduction calls | 1 |
| Total model calls | 6 |
| Reduction depth | 2 |
| Input tokens | 20,567 |
| Output tokens | 7,722 |
| Fallback shards | 0 |
| Cache hits | 0 |
| Report ID | 324 |
| Delivery ID | 297 |
| Telegram message IDs | [38, 39] |
| Delivery chunks | 2 |
| Delivery status | delivered |

## `/report new` live result

After delivering report 324 with 15 stories:
- `/report new` excluded 15 delivered stories
- `/report new` selected 30 other stories (no_new_items = False)

## Maximum tested scale

| Dimension | Maximum tested |
|-----------|---------------|
| Sources | 1,300+ (Dataset L, synthetic) |
| Raw items | 50,000+ (Dataset L, synthetic) |
| Stories in one evidence set | 8,000 (Dataset L, synthetic) |
| Stories in live report | 15 (real provider) |
| Shards in one report | 5 (live) |
| Hierarchy depth | 2 (live), bounded at 3 (config) |
| Model calls in one report | 6 (live) |

## Known limits

- Per-shard input limit: 8,000 tokens (configurable)
- Per-shard output limit: 4,000 tokens (effective)
- Map calls per report: 12 (configurable)
- Total input tokens per report: 100,000 (configurable)
- Total output tokens per report: 30,000 (configurable)
- Hierarchy depth: 3 (configurable)
- Provider output cap: 8,192 tokens (safety cap)
