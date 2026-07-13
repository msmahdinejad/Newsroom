# Implementation Tasks

## Phase 1: Foundation Setup

### Project Structure
- [ ] T001 Create Python package structure: newsroom/{sources,storage,processing,digest,cli}
- [ ] T002 Create pyproject.toml with dependencies: SQLAlchemy, Alembic, httpx, feedparser, pytest, ruff, mypy
- [ ] T003 Initialize uv environment and lock dependencies
- [ ] T004 Create .env.example with required variables
- [ ] T005 [P] Create all PowerShell script stubs in scripts/

### Database Setup
- [ ] T006 Create docker-compose.yml for PostgreSQL 16
- [ ] T007 Create SQLAlchemy models in newsroom/storage/models.py
- [ ] T008 Initialize Alembic in newsroom/storage/migrations/
- [ ] T009 Generate initial migration from models
- [ ] T010 Implement scripts/db-up.ps1 (docker compose up)
- [ ] T011 Implement scripts/db-down.ps1 (docker compose down)
- [ ] T012 Implement scripts/migrate.ps1 (alembic upgrade head)
- [ ] T013 Test full database lifecycle: up → migrate → down

**Checkpoint**: Database running, migrations applied, can query empty tables

---

## Phase 2: RSS/Atom Collection

### Source Management
- [ ] T014 Implement AbstractSource protocol in newsroom/sources/base.py
- [ ] T015 Create SourceRepository in newsroom/storage/database.py
- [ ] T016 Add seed sources to initial migration or seed script

### RSS Collector
- [ ] T017 [P] Implement RSSCollector in newsroom/sources/rss.py with httpx
- [ ] T018 [P] Add feedparser integration with error handling
- [ ] T019 [P] Add timeout configuration (30s connect, 60s read)
- [ ] T020 [P] Add content length limit (1MB)
- [ ] T021 Implement raw item storage in database
- [ ] T022 Add per-source error tracking and health status
- [ ] T023 Implement exponential backoff retry logic

### Collection CLI
- [ ] T024 Create CLI entry point in newsroom/cli/main.py using argparse
- [ ] T025 Implement collect command: fetch from all enabled sources
- [ ] T026 Add structured logging (JSON format)
- [ ] T027 Implement scripts/collect.ps1 wrapper
- [ ] T028 Implement scripts/validate-sources.ps1 (test fetch without storing)
- [ ] T029 Test with 5 real RSS feeds

**Checkpoint**: Can collect from RSS feeds, raw items in database, failed sources isolated

---

## Phase 3: GitHub Releases Collection

### GitHub Collector
- [ ] T030 Implement GitHubCollector in newsroom/sources/github.py
- [ ] T031 Add REST API integration (public repos, no auth)
- [ ] T032 Add rate limit detection and backoff
- [ ] T033 Parse release data to raw_items format
- [ ] T034 Test with 5 real repositories
- [ ] T035 Update collect command to include GitHub sources

**Checkpoint**: Can collect from both RSS and GitHub, unified storage

---

## Phase 4: Normalization Pipeline

### Normalizer
- [ ] T036 Create Normalizer class in newsroom/processing/normalize.py
- [ ] T037 [P] Implement field extraction: title, description, url, published_at
- [ ] T038 [P] Add content hash computation (SHA-256 of title+description)
- [ ] T039 [P] Add URL normalization function (lowercase domain, remove params)
- [ ] T040 Handle missing/malformed fields with defaults
- [ ] T041 Store normalized items with foreign key to raw items

### Processing CLI
- [ ] T042 Add normalize command to CLI
- [ ] T043 Process raw items in batches of 100
- [ ] T044 Implement scripts/process.ps1 wrapper
- [ ] T045 Test normalization on real collected data

**Checkpoint**: Raw items normalized, content hashes computed, URLs normalized

---

## Phase 5: Deduplication

### Deduplication Logic
- [ ] T046 Implement Deduplicator in newsroom/processing/dedupe.py
- [ ] T047 Stage 1: Exact content hash matching
- [ ] T048 Stage 2: Normalized URL matching
- [ ] T049 Mark duplicates with is_duplicate flag and duplicate_of_id
- [ ] T050 Never delete duplicates, only mark
- [ ] T051 Add deduplicate command to CLI
- [ ] T052 Test with intentional duplicate items

**Checkpoint**: Duplicates detected and marked, chains preserved

---

## Phase 6: Event Clustering

### Clustering Logic
- [ ] T053 Implement Clusterer in newsroom/processing/cluster.py
- [ ] T054 Add keyword extraction from titles (stop words removed)
- [ ] T055 Implement time window clustering (24 hours)
- [ ] T056 Calculate keyword overlap score (Jaccard similarity)
- [ ] T057 Create clusters with 50% overlap threshold
- [ ] T058 Store cluster_items relationships (many-to-many)
- [ ] T059 Add cluster command to CLI
- [ ] T060 Test with known event groups

**Checkpoint**: Items clustered by events, many-to-many relationships work

---

## Phase 7: Persian Digest Generation

### Digest Builder
- [ ] T061 Create DigestBuilder in newsroom/digest/candidate.py
- [ ] T062 Implement Persian templates in newsroom/digest/templates.py
- [ ] T063 Select most authoritative source for headline
- [ ] T064 Extract key points from cluster items
- [ ] T065 Preserve source URLs in array
- [ ] T066 Assign priority based on item count
- [ ] T067 Assign section (main vs micro) based on priority
- [ ] T068 Add digest command to CLI
- [ ] T069 Implement scripts/digest.ps1 wrapper
- [ ] T070 Test Persian output quality

**Checkpoint**: Digest candidates created with Persian text and source links

---

## Phase 8: End-to-End Pipeline

### Integration
- [ ] T071 Create pipeline orchestrator in newsroom/cli/pipeline.py
- [ ] T072 Implement scripts/run-all.ps1: collect → normalize → dedupe → cluster → digest
- [ ] T073 Add transaction safety (rollback on error)
- [ ] T074 Add progress logging for each stage
- [ ] T075 Test full pipeline with 100 real items
- [ ] T076 Measure performance (target: <5 minutes)
- [ ] T077 Add error recovery and partial completion

**Checkpoint**: Complete pipeline runs successfully, outputs Persian digests

---

## Phase 9: PowerShell Scripts & DX

### Developer Experience
- [ ] T078 Implement scripts/setup.ps1 (install deps, start db, migrate)
- [ ] T079 Implement scripts/health.ps1 (check db, test sources)
- [ ] T080 Implement scripts/reset-test-data.ps1 (truncate tables, seed)
- [ ] T081 Implement scripts/logs.ps1 (tail/grep logs)
- [ ] T082 Implement scripts/test.ps1 (pytest wrapper)
- [ ] T083 Implement scripts/lint.ps1 (ruff + mypy)
- [ ] T084 Add error handling to all scripts ($ErrorActionPreference = "Stop")
- [ ] T085 Add success/failure messages to all scripts
- [ ] T086 Document scripts in README.md

**Checkpoint**: Polished developer workflow, clear feedback

---

## Phase 10: Testing

### Test Infrastructure
- [ ] T087 Create pytest.ini with test database config
- [ ] T088 Create conftest.py with fixtures: test_db, test_session
- [ ] T089 Add test data factories

### Unit Tests
- [ ] T090 [P] Test newsroom/sources/rss.py
- [ ] T091 [P] Test newsroom/sources/github.py
- [ ] T092 [P] Test newsroom/processing/normalize.py
- [ ] T093 [P] Test newsroom/processing/dedupe.py
- [ ] T094 [P] Test newsroom/processing/cluster.py
- [ ] T095 [P] Test newsroom/digest/candidate.py

### Integration Tests
- [ ] T096 Test full collection pipeline
- [ ] T097 Test full processing pipeline
- [ ] T098 Test error handling and recovery
- [ ] T099 Test database transactions and rollback

### Contract Tests
- [ ] T100 Record RSS feed responses for replay
- [ ] T101 Record GitHub API responses for replay

**Checkpoint**: >80% coverage, tests pass, CI-ready

---

## Phase 11: Documentation & Polish

### Documentation
- [ ] T102 Write README.md with quick start
- [ ] T103 Write ADRs for key decisions
- [ ] T104 Write deployment guide for Linux VPS
- [ ] T105 Write troubleshooting guide
- [ ] T106 Write source addition guide
- [ ] T107 Document database maintenance procedures

### Final Polish
- [ ] T108 Review all code for security issues
- [ ] T109 Review all logs for secret leakage
- [ ] T110 Verify all scripts work on fresh machine
- [ ] T111 Run acceptance tests
- [ ] T112 Update STATUS.md to "MVP Complete"

**Checkpoint**: Production-ready, documented, tested

---

## Execution Notes

**Parallel Opportunities**: Tasks marked [P] can run in parallel

**Critical Path**: T001-T013 → T014-T029 → T030-T035 → T036-T045 → T046-T052 → T053-T060 → T061-T070 → T071-T077

**Estimated Effort**: 
- Phase 1: 3 days
- Phase 2: 4 days
- Phase 3: 2 days
- Phase 4: 3 days
- Phase 5: 2 days
- Phase 6: 4 days
- Phase 7: 3 days
- Phase 8: 3 days
- Phase 9: 2 days
- Phase 10: 5 days
- Phase 11: 3 days

**Total: ~34 working days (6-7 weeks)**
