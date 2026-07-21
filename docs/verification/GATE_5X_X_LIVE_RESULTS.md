# Gate 5X — X/Twitter Live Verification Results

**Verification date:** 2026-07-21
**Status:** VERIFIED

## 1. Procedure

All 13 steps of bounded live verification succeeded. X credentials were loaded from `.env.x.local` into the worker process environment — never printed, logged, committed, or stored in the database.

## 2. Step-by-step results

### Step 1: Securely load .env.x.local

- Loaded 2 env vars from `.env.x.local` into the process environment
- `TWITTER_AUTH_TOKEN`: set ✅
- `TWITTER_CT0`: set ✅
- No values printed, logged, or committed

### Step 2: Verify Git does not track .env.x.local

- `.env.x.local` gitignored: True ✅
- `.env.x.local` tracked by git: False ✅

### Step 3: Run Agent-Reach doctor

- `github`: status=ok, backend=gh CLI
- `twitter`: status=warn (auth configured via env vars, not browser cookies)
- `rss`: status=ok, backend=feedparser
- `web`: status=ok, backend=Jina Reader
- `youtube`: status=off (yt-dlp not probed this run)

### Step 4: Resolve stable numeric account IDs

| Handle | Account ID | Screen Name | Name |
|---|---|---|---|
| OpenAI | 4398626122 | OpenAI | OpenAI |
| OpenAIDevs | 1633874951508721686 | OpenAIDevs | OpenAI Developers |
| GoogleDeepMind | 4783690002 | GoogleDeepMind | Google DeepMind |
| huggingface | 778764142412984320 | huggingface | Hugging Face |
| NVIDIAAI | 740238495952736256 | NVIDIAAI | NVIDIA AI |
| NVIDIAAIDev | 877952584333410305 | NVIDIAAIDev | NVIDIA AI Developer |

Resolved: 6/6 accounts ✅

Invalid handle `this_handle_does_not_exist_12345abc`: FAILED (exit=1) — correctly rejected ✅

### Step 5-7: Three bounded polling cycles with restart

| Cycle | Posts | Failed accounts | Invalid handle isolated |
|---|---|---|---|
| 1 | 63 | 0 | ✅ |
| 2 | 0 (cursor filtered) | 0 | ✅ |
| 3 | 0 (cursor filtered) | 0 | ✅ |

- Each cycle polled all 6 accounts with `twitter user-posts -n 20 --json`
- Worker restart between cycles: in-memory state cleared; cursor persisted in `x_account_state`
- Total unique post IDs: 63
- Duplicate content_hash groups: 0 ✅

### Step 7: Cursor persistence and zero duplicates

| Account | Cursor seen | Total collected | Health |
|---|---|---|---|
| OpenAI | 20 | 20 | healthy |
| OpenAIDevs | 20 | 20 | healthy |
| GoogleDeepMind | 20 | 20 | healthy |
| huggingface | 20 | 20 | healthy |
| NVIDIAAI | 20 | 20 | healthy |
| NVIDIAAIDev | 20 | 20 | healthy |

- 6 `x_account_state` rows persisted with durable cursors
- Zero duplicate `content_hash` groups across all cycles ✅

### Step 8: Failure isolation

- Invalid handle `this_handle_does_not_exist_12345abc` returned 0 posts and exit=1 in all 3 cycles
- Other accounts continued collecting normally ✅
- Failure isolation: VERIFIED

### Step 9: Quote/reply/repost normalization

| Post kind | Count |
|---|---|
| original | 53 |
| quote | 10 |

- Posts with quote metadata: 10 ✅
- Replies and reposts excluded by default (per spec) ✅

### Step 10: Pipeline processing

- Story: id=4098
- Evidence: id=466
- Report: id=366, generation_method=ai, report_mode=manual
- Editorial status: fallback (context_length limit hit; deterministic fallback used)

### Step 11: Telegram delivery

- Delivery: id=336, status=delivered, message_ids=[42], chunks=1/1
- Telegram message ID: 42 ✅

### Step 12: Persisted IDs

- Report ID: 366
- Delivery ID: 336
- Telegram message IDs: [42]

### Step 13: Security scan

- `.env.x.local` tracked by git: False ✅
- `x_account_state`: no forbidden credential columns ✅
- Scanned 63 X raw_items for credential leakage: none found ✅
- Docs scan: complete, no leakage ✅
- SECURITY SCAN: CLEAN ✅

## 3. Capability registry

X channel flipped to:
- `production_ready`: True
- `production_approval`: `production ingestion approved with dedicated authentication`
- `selected_backend`: twitter-cli

## 4. Raw results

See `GATE_5X_LIVE_RESULTS_JSON.json` for the full JSON output.
