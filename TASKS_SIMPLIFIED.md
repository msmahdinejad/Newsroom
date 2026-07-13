# Implementation Tasks (Simplified)

## Milestone 1: Local Foundation

**Goal**: Working Python project with PostgreSQL, configuration, migrations, health checks

### M1.1 Project Structure (5 tasks)
- [ ] T101 Create src/newsroom/ package structure and pyproject.toml with uv
- [ ] T102 Create Docker Compose with PostgreSQL 16 and .env.example
- [ ] T103 Create SQLAlchemy models for sources, raw_items, normalized_items, stories, digests
- [ ] T104 Initialize Alembic migrations and generate initial schema
- [ ] T105 Create scripts/ directory with all PowerShell stubs

### M1.2 Core Infrastructure (5 tasks)
- [ ] T106 Implement config loading (env vars, defaults, validation)
- [ ] T107 Implement source registry database access layer
- [ ] T108 Implement structured logging (JSON format, levels)
- [ ] T109 Create newsroom CLI entry point with health, db migrate commands
- [ ] T110 Create PowerShell scripts: setup.ps1, db-up.ps1, db-down.ps1, migrate.ps1, health.ps1

### M1.3 Testing & Verification (2 tasks)
- [ ] T111 Create pytest infrastructure with test DB fixtures
- [ ] T112 Verify M1: uv sync, docker compose up, migrations, health command, tests pass

**Exit Criteria**: Scripts work on Windows PowerShell, database migrates, health command runs, basic tests pass

---

## Milestone 2: First Complete Pipeline

**Goal**: End-to-end RSS/GitHub → storage → processing → deduplication → story → Persian preview

### M2.1 Collection (4 tasks)
- [ ] T201 Implement RSS/Atom collector with httpx, feedparser, timeout, error isolation
- [ ] T202 Implement GitHub releases collector with rate limit handling
- [ ] T203 Store raw items with source tracking and health status
- [ ] T204 Create collect.ps1, validate-sources.ps1, seed 3-5 test sources

### M2.2 Processing Pipeline (5 tasks)
- [ ] T205 Implement normalization: extract title, description, url, published_at, content_hash
- [ ] T206 Implement deterministic deduplication: content hash → URL normalization → mark duplicates
- [ ] T207 Implement story creation: group by content hash or manual grouping
- [ ] T208 Implement Persian digest preview using simple templates with source links
- [ ] T209 Create process.ps1, digest.ps1 scripts

### M2.3 Integration & Testing (3 tasks)
- [ ] T210 Create run-all.ps1: collect → process → digest in one command
- [ ] T211 Add tests for collection, normalization, deduplication, story creation
- [ ] T212 Verify M2: Full pipeline produces Persian digest with preserved source links

**Exit Criteria**: Can run full pipeline from RSS/GitHub → Persian preview, sources preserved

---

## Milestone 3: Hermes Editorial & Telegram Delivery

**Goal**: Hermes-synthesized Persian reports delivered to Telegram

### M3.1 Hermes Integration (3 tasks)
- [ ] T301 Create digest candidate packet format for Hermes input
- [ ] T302 Create Persian editorial skill in project (not global profile)
- [ ] T303 Implement Hermes synthesis call: candidates → final Persian report

### M3.2 Telegram Delivery (4 tasks)
- [ ] T304 Implement Telegram-safe chunking (4096 chars, preserve markdown)
- [ ] T305 Implement Telegram Bot delivery with exponential backoff
- [ ] T306 Implement report archival (store sent digests with timestamps)
- [ ] T307 Create telegram-send.ps1 script for manual testing

### M3.3 Scheduling & Operations (3 tasks)
- [ ] T308 Create test-schedule.ps1 for manual dry-run
- [ ] T309 Add scripts: logs.ps1, reset-test-data.ps1
- [ ] T310 Verify M3: Manual schedule → Hermes synthesis → Telegram delivery → archive

**Exit Criteria**: Can manually trigger pipeline that sends Persian digest to Telegram via Bot

---

## Milestone 4: Expanded Sources & Production (Future)

**Not implemented now. Later adds**:
- Telegram channel monitoring (auth required)
- Agent-Reach integration
- WorldMonitor integration  
- YouTube monitoring
- Additional social sources
- Three daily cron schedules (morning, afternoon, evening)
- Automated backups
- Monitoring and alerts
- Linux VPS deployment
- Production documentation

---

## Execution Order

**Critical path**: M1 → M2 → M3

**Current focus**: Milestone 1 (T101-T112)

**Estimated effort**: 
- M1: 2-3 days
- M2: 3-4 days  
- M3: 2-3 days
- Total: ~1.5-2 weeks for working MVP

**Total tasks**: 29 active tasks (M1-M3 only)
