# M2: First Complete Pipeline

**Goal**: End-to-end vertical slice from RSS/GitHub collection → Persian digest preview

**Acceptance**: Run pipeline twice, second run produces no duplicates, Persian preview exists

## Architecture

```
Sources (RSS/GitHub) 
  → Raw Storage (immutable JSON)
    → Normalization (title, URL, hash)
      → Deduplication (exact + fuzzy)
        → Story Clustering (by keywords)
          → Persian Preview (deterministic template)
```

## Implementation Sequence

### Phase A: RSS Collection (Vertical Slice)
1. `src/newsroom/sources/rss.py` - RSSCollector with httpx + feedparser
2. Timeout: 30s connect, 60s read (from config)
3. Size limit: 1MB (from config)
4. Store raw JSON in `raw_items` table
5. Error handling: catch per-source, mark health status
6. CLI command: `newsroom collect --source-type rss`
7. Test with 3 real RSS feeds (Python blog, PyPI, GitHub blog)

**Checkpoint**: Can collect RSS, raw items stored, failures isolated

### Phase B: GitHub Releases Collection
1. `src/newsroom/sources/github.py` - GitHubCollector
2. Use public REST API: `/repos/{owner}/{repo}/releases`
3. No auth for now (60 req/hour rate limit)
4. Store as raw items with type=github_releases
5. Detect rate limits, exponential backoff
6. CLI command: `newsroom collect --source-type github`
7. Test with 3 repos (pytorch/pytorch, python/cpython, pydantic/pydantic)

**Checkpoint**: Can collect from both source types

### Phase C: Normalization Pipeline
1. `src/newsroom/processing/normalize.py` - Normalizer class
2. Extract: title, description, source_url, published_at
3. Compute content_hash: SHA-256(title + description)
4. Normalize URL: lowercase domain, strip tracking params
5. Store in `normalized_items` table with FK to raw_items
6. CLI command: `newsroom process normalize`
7. Batch processing: 100 items at a time

**Checkpoint**: Raw items → normalized items, hashes computed

### Phase D: Deduplication
1. `src/newsroom/processing/dedupe.py` - Deduplicator class
2. Stage 1: Exact content_hash match → mark duplicate
3. Stage 2: Normalized URL match → mark duplicate
4. Never delete, only mark with `is_duplicate=True` and `duplicate_of_id`
5. CLI command: `newsroom process dedupe`
6. Test: insert intentional duplicates, verify detection

**Checkpoint**: Duplicates marked, chains preserved

### Phase E: Story Clustering
1. `src/newsroom/processing/cluster.py` - Clusterer class
2. Keyword extraction: simple word frequency from title+description
3. Similarity threshold: 0.5 (from config)
4. Group normalized_items into `stories` table
5. Store source_urls (JSON array) and item_ids (JSON array)
6. CLI command: `newsroom process cluster`

**Checkpoint**: Items grouped into stories

### Phase F: Persian Preview (Deterministic)
1. `src/newsroom/digest/preview.py` - PreviewGenerator class
2. Template-based, NO LLM yet
3. Sections:
   - مهم‌ترین خبرها (high priority stories)
   - ریزخبرها (low priority, compact)
4. Format per story:
   - Headline (from story.headline)
   - Source count
   - URLs (all sources)
5. Store in `digests` table
6. CLI command: `newsroom digest preview`

**Checkpoint**: Persian digest exists with source attribution

### Phase G: Integration & Idempotency
1. `newsroom pipeline run` - runs all phases in sequence
2. Cursor/checkpoint: track last processed raw_item_id per phase
3. Run twice on same data → no duplicates created
4. Error in phase N doesn't corrupt phases 1..N-1
5. Can restart from any phase

**Checkpoint**: Complete pipeline idempotent

## Verification Gates

After all phases complete:

```powershell
# 1. Collect from sources
uv run newsroom collect

# 2. Verify raw items
docker compose exec postgres psql -U newsroom -d newsroom -c "SELECT COUNT(*) FROM raw_items;"
# Expected: > 0

# 3. Process pipeline
uv run newsroom process normalize
uv run newsroom process dedupe
uv run newsroom process cluster

# 4. Generate preview
uv run newsroom digest preview

# 5. Verify digest
docker compose exec postgres psql -U newsroom -d newsroom -c "SELECT content_fa FROM digests ORDER BY created_at DESC LIMIT 1;"
# Expected: Persian text with URLs

# 6. Run complete pipeline
uv run newsroom pipeline run

# 7. Idempotency test - run again
uv run newsroom pipeline run
docker compose exec postgres psql -U newsroom -d newsroom -c "SELECT COUNT(*) FROM normalized_items WHERE is_duplicate=false;"
# Expected: Same count as before

# 8. Integration tests
uv run pytest tests/test_pipeline.py -v
```

## Files to Create

```
src/newsroom/
├── sources/
│   ├── base.py              # AbstractSource protocol
│   ├── rss.py               # RSSCollector
│   └── github.py            # GitHubCollector
├── processing/
│   ├── normalize.py         # Normalizer
│   ├── dedupe.py            # Deduplicator
│   └── cluster.py           # Clusterer
├── digest/
│   └── preview.py           # PreviewGenerator (templates)
└── cli/
    └── commands/
        ├── collect.py       # Collection commands
        ├── process.py       # Processing commands
        ├── digest.py        # Digest commands
        └── pipeline.py      # Integrated pipeline

tests/
├── test_rss.py
├── test_github.py
├── test_normalize.py
├── test_dedupe.py
├── test_cluster.py
├── test_preview.py
└── test_pipeline.py

fixtures/
├── sample_rss.xml
├── sample_github_releases.json
└── expected_persian_preview.txt
```

## Source Seeding

Add to migration or seed script:

```sql
-- RSS sources
INSERT INTO sources (name, type, url, language, priority, enabled) VALUES
('Python Blog', 'rss', 'https://blog.python.org/feeds/posts/default', 'en', 'high', true),
('PyPI New Releases', 'rss', 'https://pypi.org/rss/updates.xml', 'en', 'medium', true),
('GitHub Engineering', 'rss', 'https://github.blog/feed/', 'en', 'medium', true);

-- GitHub sources
INSERT INTO sources (name, type, url, language, priority, enabled) VALUES
('PyTorch Releases', 'github_releases', 'pytorch/pytorch', 'en', 'high', true),
('Python CPython', 'github_releases', 'python/cpython', 'en', 'high', true),
('Pydantic', 'github_releases', 'pydantic/pydantic', 'en', 'medium', true);
```

## Persian Template Example

```
📰 گزارش خبری هوش مصنوعی
تاریخ: {date}

━━━━━━━━━━━━━━━━━━
🔥 مهم‌ترین خبرها
━━━━━━━━━━━━━━━━━━

{story.headline}
منابع: {source_count} منبع
🔗 {url1}
🔗 {url2}

━━━━━━━━━━━━━━━━━━
📌 ریزخبرها
━━━━━━━━━━━━━━━━━━

• {item.title} [{source_name}]
```

## Non-Goals (Deferred to M3)

- LLM synthesis (M3)
- Telegram delivery (M3)
- Advanced clustering algorithms
- Multi-language detection
- Agent-Reach integration (M4)
- WorldMonitor integration (M4)
- YouTube/X/Reddit sources (M4)

## Success Criteria

- [ ] Can collect from 6 sources (3 RSS, 3 GitHub)
- [ ] Raw items stored with source attribution
- [ ] Normalization extracts all fields correctly
- [ ] Duplicates detected across both exact hash and URL
- [ ] Stories cluster items by keyword similarity
- [ ] Persian preview readable with source links preserved
- [ ] Pipeline runs end-to-end without manual intervention
- [ ] Idempotency: second run produces no new duplicates
- [ ] All M2 tests pass
- [ ] Failed source doesn't break others
- [ ] Can restart pipeline from any phase
