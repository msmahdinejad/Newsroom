# Milestone Plan

## Milestone 1: Foundation (Week 1)
**Goal**: Project structure, database, basic collection

**Deliverables**:
- [ ] Repository structure created
- [ ] Python environment with uv configured
- [ ] Docker Compose for PostgreSQL running
- [ ] SQLAlchemy models defined
- [ ] Alembic migrations working
- [ ] PowerShell scripts: db-up, db-down, migrate
- [ ] Database schema created and verified

**Success Criteria**:
- `scripts/db-up.ps1` starts PostgreSQL
- `scripts/migrate.ps1` applies migrations
- Can connect to database and query tables
- All models have proper relationships

**Blocked By**: None

---

## Milestone 2: RSS Collection (Week 1-2)
**Goal**: Collect and store raw RSS/Atom feeds

**Deliverables**:
- [ ] RSS/Atom collector implemented
- [ ] httpx with timeout and error handling
- [ ] feedparser integration
- [ ] Raw items stored in database
- [ ] Per-source error isolation
- [ ] PowerShell scripts: collect.ps1, validate-sources.ps1
- [ ] Test with 5 real RSS feeds

**Success Criteria**:
- Can fetch from any RSS/Atom feed
- Failed source doesn't stop others
- Raw data preserved exactly
- Health status tracked per source
- `scripts/collect.ps1` runs successfully

**Blocked By**: Milestone 1 (database must exist)

---

## Milestone 3: GitHub Releases (Week 2)
**Goal**: Collect GitHub release data

**Deliverables**:
- [ ] GitHub releases collector implemented
- [ ] REST API integration (public, no auth)
- [ ] Rate limit handling
- [ ] Store releases as raw items
- [ ] Test with 5 real repositories

**Success Criteria**:
- Can fetch releases from any public repo
- Respects rate limits (60 req/hour)
- Release data stored consistently
- Works alongside RSS collection

**Blocked By**: Milestone 2 (collector architecture established)

---

## Milestone 4: Normalization (Week 2)
**Goal**: Transform raw items to standard schema

**Deliverables**:
- [ ] Normalization pipeline implemented
- [ ] Extract: title, description, url, published_at
- [ ] Content hash computation (SHA-256)
- [ ] URL normalization function
- [ ] Handle missing/malformed fields
- [ ] PowerShell script: process.ps1

**Success Criteria**:
- All raw items normalized successfully
- Content hashes unique for distinct content
- URLs normalized consistently
- `scripts/process.ps1` runs successfully

**Blocked By**: Milestone 2 (needs raw items to process)

---

## Milestone 5: Deduplication (Week 3)
**Goal**: Identify and mark duplicate items

**Deliverables**:
- [ ] Content hash deduplication
- [ ] URL normalization deduplication
- [ ] Mark duplicates, don't delete
- [ ] Track duplicate_of relationship
- [ ] Test with intentional duplicates

**Success Criteria**:
- Exact duplicates detected (100% precision)
- URL variants detected (example.com vs example.com?utm=x)
- No false positives on different content
- Duplicate chain preserved (A→B→C)

**Blocked By**: Milestone 4 (needs normalized items)

---

## Milestone 6: Event Clustering (Week 3-4)
**Goal**: Group items about same event

**Deliverables**:
- [ ] Time-window clustering (24 hours)
- [ ] Keyword extraction from titles
- [ ] Keyword overlap scoring (50% threshold)
- [ ] Many-to-many cluster_items table
- [ ] Test with known event groups

**Success Criteria**:
- Items about "Python 3.13 released" grouped together
- Items about different events separated
- Borderline cases handled (manual review flag)
- Each item can belong to multiple clusters if needed

**Blocked By**: Milestone 5 (needs unique items)

---

## Milestone 7: Persian Digest Candidates (Week 4)
**Goal**: Generate Persian summaries with source links

**Deliverables**:
- [ ] Template-based Persian generation
- [ ] Headline from most authoritative source
- [ ] Key points list from cluster
- [ ] Source attribution preserved
- [ ] Priority scoring (simple: item count)
- [ ] Section assignment (main vs micro)

**Success Criteria**:
- Every digest candidate has headline_fa
- Source URLs preserved in array
- Can distinguish important vs minor items
- Output ready for human review

**Blocked By**: Milestone 6 (needs event clusters)

---

## Milestone 8: End-to-End Pipeline (Week 4-5)
**Goal**: Complete pipeline from collection to digest

**Deliverables**:
- [ ] scripts/run-all.ps1 executes full pipeline
- [ ] Integration test with real sources
- [ ] Error handling at each stage
- [ ] Transaction safety (rollback on error)
- [ ] Logging throughout pipeline
- [ ] Performance benchmarks

**Success Criteria**:
- Can run full pipeline in <5 minutes for 100 items
- Errors logged but don't stop pipeline
- Output digest candidates ready for review
- All PowerShell scripts documented

**Blocked By**: Milestone 7 (needs all stages)

---

## Milestone 9: Developer Experience (Week 5)
**Goal**: Polished local development workflow

**Deliverables**:
- [ ] All PowerShell scripts with error handling
- [ ] scripts/setup.ps1 for new developer onboarding
- [ ] scripts/health.ps1 for system check
- [ ] scripts/reset-test-data.ps1 for clean state
- [ ] scripts/test.ps1 for running pytest
- [ ] scripts/lint.ps1 for ruff + mypy
- [ ] scripts/logs.ps1 for viewing logs
- [ ] README.md with quick start

**Success Criteria**:
- New developer can run setup.ps1 and start working
- All scripts return clear success/failure
- Health check catches common issues
- Tests run reliably

**Blocked By**: Milestone 8 (needs working pipeline)

---

## Milestone 10: Testing & Quality (Week 5-6)
**Goal**: Comprehensive test coverage

**Deliverables**:
- [ ] Unit tests for each module
- [ ] Integration tests for pipeline stages
- [ ] Contract tests for external APIs (recorded)
- [ ] Test database separate from dev
- [ ] pytest fixtures for common setups
- [ ] CI-ready test suite

**Success Criteria**:
- >80% code coverage
- All tests pass consistently
- Tests run in <2 minutes
- Can run tests without network access

**Blocked By**: Milestone 9 (needs stable codebase)

---

## Milestone 11: Documentation (Week 6)
**Goal**: Complete documentation for handoff

**Deliverables**:
- [ ] Architecture decision records (ADRs)
- [ ] Deployment guide for Linux VPS
- [ ] Troubleshooting guide
- [ ] Source addition guide
- [ ] Database maintenance guide
- [ ] Acceptance test results

**Success Criteria**:
- Another developer can deploy to VPS
- Common issues have documented solutions
- All design decisions explained

**Blocked By**: Milestone 10 (needs stable system)

---

## Release Criteria (MVP Complete)

All of the following must be true:
- [ ] All 11 milestones complete
- [ ] Acceptance tests pass
- [ ] Performance meets targets (<5 min for 100 items)
- [ ] Security checklist complete
- [ ] Documentation complete
- [ ] Source policy enforced
- [ ] Data retention working
- [ ] PowerShell scripts all working
- [ ] Can run full pipeline manually
- [ ] Test data reset works

**Estimated Timeline**: 6 weeks from start

**Dependencies Met**: 
- Windows 10/11 with Docker Desktop
- Python 3.12 + uv installed
- PowerShell 5.1 or 7
- PostgreSQL via Docker
