# Database Schema

## Tables

### sources
Configuration for each external source.

```sql
CREATE TABLE sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    type VARCHAR(50) NOT NULL,  -- 'rss', 'atom', 'github_releases'
    url TEXT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    priority VARCHAR(20) DEFAULT 'medium',  -- 'high', 'medium', 'low'
    language VARCHAR(10),  -- 'en', 'fa', 'ar'
    categories TEXT[],  -- ['python', 'ai', 'releases']
    health_status VARCHAR(20) DEFAULT 'healthy',  -- 'healthy', 'degraded', 'failing', 'disabled'
    last_fetch_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_error TEXT,
    consecutive_failures INT DEFAULT 0,
    metadata JSONB,  -- Source-specific config
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sources_enabled ON sources(enabled) WHERE enabled = TRUE;
CREATE INDEX idx_sources_health ON sources(health_status);
```

### raw_items
Unprocessed content exactly as received from sources.

```sql
CREATE TABLE raw_items (
    id SERIAL PRIMARY KEY,
    source_id INT NOT NULL REFERENCES sources(id),
    external_id VARCHAR(512),  -- Source's ID for item (GUID, URL, etc)
    raw_data JSONB NOT NULL,  -- Complete original response
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_raw_items_source ON raw_items(source_id);
CREATE INDEX idx_raw_items_processed ON raw_items(processed) WHERE processed = FALSE;
CREATE INDEX idx_raw_items_external ON raw_items(source_id, external_id);
CREATE INDEX idx_raw_items_collected ON raw_items(collected_at DESC);
```

### normalized_items
Processed items in standard schema.

```sql
CREATE TABLE normalized_items (
    id SERIAL PRIMARY KEY,
    raw_item_id INT NOT NULL REFERENCES raw_items(id),
    source_id INT NOT NULL REFERENCES sources(id),
    title TEXT NOT NULL,
    description TEXT,
    content TEXT,
    source_url TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    author VARCHAR(255),
    content_hash CHAR(64) NOT NULL,  -- SHA-256 hex
    url_normalized TEXT NOT NULL,
    language VARCHAR(10),
    is_duplicate BOOLEAN DEFAULT FALSE,
    duplicate_of_id INT REFERENCES normalized_items(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_normalized_source ON normalized_items(source_id);
CREATE INDEX idx_normalized_hash ON normalized_items(content_hash);
CREATE INDEX idx_normalized_url ON normalized_items(url_normalized);
CREATE INDEX idx_normalized_published ON normalized_items(published_at DESC);
CREATE INDEX idx_normalized_duplicates ON normalized_items(is_duplicate) WHERE is_duplicate = FALSE;
```

### event_clusters
Groups of items about the same event.

```sql
CREATE TABLE event_clusters (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    keywords TEXT[],
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    item_count INT DEFAULT 0,
    priority VARCHAR(20) DEFAULT 'medium',  -- For digest ordering
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_clusters_time ON event_clusters(start_time, end_time);
CREATE INDEX idx_clusters_priority ON event_clusters(priority);
```

### cluster_items
Many-to-many relationship between clusters and items.

```sql
CREATE TABLE cluster_items (
    cluster_id INT NOT NULL REFERENCES event_clusters(id) ON DELETE CASCADE,
    item_id INT NOT NULL REFERENCES normalized_items(id) ON DELETE CASCADE,
    relevance_score FLOAT DEFAULT 1.0,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cluster_id, item_id)
);

CREATE INDEX idx_cluster_items_cluster ON cluster_items(cluster_id);
CREATE INDEX idx_cluster_items_item ON cluster_items(item_id);
```

### digest_candidates
Persian-language digest entries ready for publication.

```sql
CREATE TABLE digest_candidates (
    id SERIAL PRIMARY KEY,
    cluster_id INT NOT NULL REFERENCES event_clusters(id),
    headline_fa TEXT NOT NULL,
    summary_fa TEXT NOT NULL,
    key_points_fa TEXT[],
    source_urls TEXT[] NOT NULL,
    published_at TIMESTAMPTZ,
    priority VARCHAR(20) DEFAULT 'medium',
    section VARCHAR(50) DEFAULT 'main',  -- 'main' or 'micro'
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_digest_cluster ON digest_candidates(cluster_id);
CREATE INDEX idx_digest_published ON digest_candidates(published_at DESC) WHERE published_at IS NOT NULL;
CREATE INDEX idx_digest_section ON digest_candidates(section);
```

## Data Flow

```
sources → raw_items → normalized_items → event_clusters ← cluster_items
                                              ↓
                                        digest_candidates
```

## Constraints

### Referential Integrity
- raw_items.source_id → sources.id (ON DELETE CASCADE)
- normalized_items.raw_item_id → raw_items.id (ON DELETE CASCADE)
- cluster_items → both tables (ON DELETE CASCADE)
- digest_candidates.cluster_id → event_clusters.id (ON DELETE RESTRICT)

### Unique Constraints
- sources.name (unique)
- raw_items(source_id, external_id) (unique per source)

### Check Constraints
- sources.priority IN ('high', 'medium', 'low')
- sources.health_status IN ('healthy', 'degraded', 'failing', 'disabled')
- digest_candidates.section IN ('main', 'micro')

## Indexes Strategy

### Performance Indexes
- Collection queries: source_id, processed flag
- Deduplication: content_hash, url_normalized
- Time-range queries: published_at, collected_at
- Clustering: published_at range scans

### Maintenance
- VACUUM ANALYZE weekly
- REINDEX monthly
- Monitor index usage with pg_stat_user_indexes

## Estimated Sizes (1 Year)

Assumptions: 1000 items/day, 100 sources

- sources: ~100 rows = <1MB
- raw_items: ~365K rows × 2KB = ~730MB (with 90-day retention: ~180MB)
- normalized_items: ~365K rows × 1KB = ~365MB (with 180-day retention: ~180MB)
- event_clusters: ~36K rows × 500B = ~18MB
- cluster_items: ~365K rows × 20B = ~7MB
- digest_candidates: ~36K rows × 2KB = ~72MB

**Total: ~450MB** (with retention policies applied)

## Migrations

Managed by Alembic:
- Version controlled in `newsroom/storage/migrations/versions/`
- Auto-generated from model changes
- Manual review before apply
- Rollback scripts included
