# Gate 5 — YouTube Adapter

**Verification date:** 2026-07-18
**Pinned Agent-Reach revision:** `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (v1.5.0)
**Selected backend:** yt-dlp
**Production approval:** `production ingestion approved`

## 1. Adapter

`YouTubeCollector` (`src/newsroom/sources/agent_reach/adapters.py`)

## 2. Production scope

- Curated public channel allowlist only.
- New video metadata: title, description, publication timestamp, stable channel ID, stable video ID, canonical URL.
- Optional public subtitle text when safely available (bounded by size, language, timeout, and evidence-excerpt limits).
- Durable per-channel cursor (last stable video ID + bounded seen_item_ids set, last 200).
- Deduplication by video ID at the raw-item content_hash layer.

## 3. Out of scope

- Downloading full video files.
- Archiving media.
- Collecting comments.
- Collecting private videos.
- Unlimited keyword discovery.
- Processing arbitrary user-submitted URLs.
- Persisting enormous transcripts without limits.

## 4. Identity

- Stable platform identity: video ID (11 chars) + channel ID (`UC` + 22 chars).
- Display names are NOT used as the sole identity.
- AI-generated titles or summaries are NOT used as deduplication identities.
- `agent_reach_raw_content_hash` for YouTube = `sha256("yt:{video_id}:{channel_id}")`.

## 5. Bounded real-read verification (2026-07-18)

### Channel read

```
yt-dlp --dump-json --no-playlist --flat-playlist --playlist-end 3 \
  "https://www.youtube.com/@YannicKilcher/videos"
```

Result: 3 video metadata entries returned.

### Item collected into the Newsroom pipeline

- Video ID: `xHi8PUIVyoo`
- Title: "I built a fully autonomous mansplainer"
- Channel: Yannic Kilcher
- Canonical URL: `https://www.youtube.com/watch?v=xHi8PUIVyoo`
- Raw item persisted: `raw_items.id = 2074`, `content_hash = sha256("yt:xHi8PUIVyoo:<channel_id>")`.

### Pipeline flow

1. **Collection:** `raw_items.id = 2074` persisted with `type = youtube`.
2. **Normalization:** `normalized_items.id = 1453` persisted with stable identity.
3. **Story creation:** `stories.id = 4093` created with headline from the video title.
4. **Evidence:** `evidence.id = 433` created with a facts list and source URL.
5. **AI editorial:** `reports.id = 364` produced via the Gate 4 editorial orchestrator; `generation_method = ai`; Persian content rendered.
6. **Telegram delivery:** `deliveries.id = 335`, `status = delivered`, `message_ids = [41]`, `delivered_chunks = 1/1`.

### Persian report excerpt

```
📰 گزارش خبری هوش مصنوعی و فناوری

تاریخ: 2026-07-18
نوع گزارش: فوری

📰 ریزخبرها

• انتشار ویدیوی جدید یانیک کیلچر با عنوان «من یک من‌اسپلینر کاملاً خودکار ساختم» |
  🔗 https://www.youtube.com/watch?v=xHi8PUIVyoo

📊 این گزارش شامل 1 خبر از منابع مختلف است
🤖 تولید شده توسط هوش مصنوعی
⏰ 17:26 UTC
```

## 6. Doctor output

```
youtube: status=warn, active_backend=yt-dlp, tier=0
```

The `warn` status is because yt-dlp's full probe requires a JS runtime. The backend IS installed and the bounded real read succeeded. The registry treats `warn` as `available=True` (healthy) and records the production-ready flag after the bounded real read.

## 7. Cursor and restart behavior

- Cursor shape: `{"last_stable_item_id": "<video_id>", "seen_item_ids": ["<video_id>", ...]}`.
- The `seen_item_ids` list is bounded to the last 200 entries.
- On restart, `filter_new_items` drops items whose video ID is in `seen_item_ids`.
- Overlap is retained for idempotency: a duplicate video ID is caught by the raw-item `content_hash` dedup layer.
- Verified by `test_durable_cursor_advances_for_youtube`, `test_durable_cursor_filters_seen_items`, `test_durable_cursor_keeps_overlap_for_idempotency`, `test_repeated_polling_advances_cursor`, and the integration test `test_restart_continues_from_persisted_cursor`.

## 8. Edit behavior

- Same video ID + channel ID → same `content_hash`. An edited video (new title/description) does NOT create a new raw item; the pipeline updates the existing raw item's `raw_data` in place.
- Verified by `test_youtube_edit_changes_raw_content_hash_only_if_id_changes` and the integration test `test_item_edit_updates_existing_raw_item`.

## 9. Rate-limit handling

- A rate-limit failure is recorded via `registry.mark_failure("youtube", category="rate_limit")`.
- The registry entry flips to `healthy=False`, `degraded=True`, `failure_category="rate_limit"`, `production_ready=False`.
- `agent_reach_source_state.rate_limit_state` and `agent_reach_source_state.retry_after` persist the rate-limit state across restarts.
- Verified by `test_rate_limit_state_recorded_in_backend_state` and the integration test `test_rate_limit_state_persisted_in_source_state`.

## 10. Subtitle text (optional, not yet exercised live)

The adapter supports a `write-subs` operation (allowlisted) for fetching public subtitles. The production scope applies transcript size, language (en./fa.), timeout, and evidence-excerpt limits. Subtitle fetching was not exercised in the Gate 5 bounded live verification but the capability is available and bounded by the same controlled runner.

## 11. Production approval

`production ingestion approved` — yt-dlp is installed, the bounded real read succeeded, the item flowed through the full pipeline to a delivered Persian Telegram report, cursor and restart behavior work, edit behavior is correct, and rate-limit handling is in place.
