# Architecture Overview

## System Context

```
┌─────────────────────────────────────────────────────────┐
│                  External Sources                        │
│  RSS Feeds │ Atom Feeds │ GitHub Releases │ (future)    │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTPS
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Persian AI Newsroom (Local)                 │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ Collection │─▶│ Processing   │─▶│ Digest Gen     │  │
│  │  (async)   │  │ (deterministic)│ │ (Persian)      │  │
│  └────────────┘  └──────────────┘  └────────────────┘  │
│         │                │                   │           │
│         └────────────────┴───────────────────┘           │
│                          ▼                               │
│                 ┌────────────────┐                       │
│                 │  PostgreSQL 16 │                       │
│                 │  (Docker)      │                       │
│                 └────────────────┘                       │
└─────────────────────────────────────────────────────────┘
```

## Module Structure

```
newsroom/
├── sources/          # Collection from external sources
│   ├── base.py      # AbstractSource protocol
│   ├── rss.py       # RSS/Atom collector
│   └── github.py    # GitHub releases collector
├── storage/         # Database layer
│   ├── models.py    # SQLAlchemy models
│   ├── database.py  # Connection management
│   └── migrations/  # Alembic migrations
├── processing/      # Deterministic processing
│   ├── normalize.py # Raw → Normalized transformation
│   ├── dedupe.py    # Deduplication algorithms
│   └── cluster.py   # Event clustering
├── digest/          # Persian output generation
│   ├── candidate.py # Digest candidate builder
│   └── templates.py # Persian templates
└── cli/             # Command-line interface
    └── main.py      # CLI entry point
```

## Data Flow

### 1. Collection Phase
```
Source → httpx GET → Raw Response → PostgreSQL (raw_items)
```
- Each source fetched independently
- Errors logged but don't stop other sources
- Raw response stored exactly as received

### 2. Normalization Phase
```
raw_items → Parse/Extract → normalized_items
```
- Extract: title, description, published_at, source_url
- Compute content_hash (SHA-256)
- Store normalized form

### 3. Deduplication Phase
```
normalized_items → Hash/URL Match → unique items marked
```
- Stage 1: Exact content hash match
- Stage 2: Normalized URL match
- Duplicates marked, not deleted

### 4. Clustering Phase
```
unique items → Time Window + Keywords → event_clusters
```
- 24-hour time windows
- Keyword extraction from titles
- 50% keyword overlap threshold
- Many-to-many: items can appear in multiple clusters

### 5. Digest Generation Phase
```
event_clusters → Template Fill → digest_candidates
```
- Persian headline from cluster
- Key points from member items
- Source URLs preserved
- Priority scoring (future: use AI)

## Technology Decisions

### Python 3.12 + uv
- Fast dependency resolution
- Reproducible builds
- Native Windows support
- Virtual environment managed by uv

### PostgreSQL 16
- JSONB for raw storage
- Full-text search (future)
- Time-series queries efficient
- Docker ensures consistency

### SQLAlchemy 2 + Alembic
- Type-safe ORM
- Async support
- Migration tracking
- Cross-platform

### httpx
- Async HTTP client
- Connection pooling
- Timeout handling
- Better than requests for high-volume

### feedparser
- Battle-tested RSS/Atom parser
- Handles malformed feeds
- Standard library feel

## Deployment Models

### Development (Windows)
```
Developer Machine
├── Python (native via uv)
├── PostgreSQL (Docker Desktop)
└── Scripts (PowerShell)
```

### Production (Linux VPS - Future)
```
Docker Compose
├── app container (Python)
├── db container (PostgreSQL)
└── Volume mounts for data persistence
```

## Scalability Considerations

### Current Limits (MVP)
- ~100 sources
- ~10K items/day
- Single-machine processing
- Manual execution

### Future Scaling
- Horizontal: Multiple workers for collection
- Vertical: Larger PostgreSQL instance
- Caching: Redis for dedupe lookups
- Queue: Celery for background processing

## Error Handling Strategy

### Per-Source Isolation
- Source errors don't cascade
- Failed sources retried independently
- Exponential backoff: 1m, 5m, 15m, 1h

### Data Integrity
- Transactions for multi-table updates
- Foreign key constraints enforced
- No orphaned records

### Logging
- Structured JSON logs
- Per-source success/failure
- Timing metrics for each phase
- Error details with stack traces

## Security Boundaries

### Trust Zones
1. **External Sources**: Untrusted, parse defensively
2. **Database**: Trusted, validated data only
3. **Digest Output**: Trusted, safe for publishing

### Input Validation
- Max content length: 1MB per item
- URL validation before storage
- HTML sanitization in descriptions
- No JavaScript execution

### Secret Management
- Environment variables only
- Never in code or logs
- `.env` for local development
- Docker secrets for production
