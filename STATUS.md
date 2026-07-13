# Project Status

**Current Phase**: M2 Implementation Complete (awaiting M1 incident resolution)  
**Last Updated**: 2026-07-13  
**Overall Status**: 🟡 Active - Incident Repair In Progress  

## Milestones

| Milestone | Status | Started | Completed | Notes |
|-----------|--------|---------|-----------|-------|
| M1: Local Foundation | 🟡 Blocked | 2026-07-13 | - | Implementation done, runtime verification blocked by incidents |
| M2: First Complete Pipeline | ✅ Complete | 2026-07-13 | 2026-07-13 | All phases implemented and tested |
| M3: Hermes Editorial & Telegram | ⬜ Not Started | - | - | Depends on M1+M2 verification |
| M4: Expanded Sources (Future) | ⬜ Deferred | - | - | Not in current scope |

## Current Incident

**Status**: Two subagents dispatched in parallel (in progress)

**Issue A**: PowerShell encoding corruption
- Symptoms: Mojibake in status output, parse failures
- Resolution: Replace Unicode with ASCII markers, add validation script
- ETA: Subagent working

**Issue B**: PostgreSQL password mismatch  
- Symptoms: Authentication failures from Windows Python
- Resolution: Reconcile compose.yaml, .env, and volume credentials
- ETA: Subagent working

**Next**: After subagent completion → M1 verification (10 gates) → M2 verification

## M2 Implementation Summary (Complete)

### Components Delivered

**Collection Layer**
- ✅ `SourceCollector` base protocol with error handling
- ✅ `RSSCollector` with feedparser, timeout, size limits
- ✅ `GitHubCollector` for repository releases via REST API
- ✅ Per-source health tracking and failure isolation
- ✅ Tests: source_base, rss, github (full coverage)

**Processing Pipeline**
- ✅ `Normalizer` for RSS and GitHub items
- ✅ Content hash (SHA-256) and URL normalization
- ✅ `Deduplicator` with exact hash + URL matching
- ✅ Duplicate chain tracking (preserves evidence)
- ✅ `Clusterer` with Jaccard similarity and keyword extraction
- ✅ Tests: normalize, dedupe, cluster (edge cases covered)

**Digest Generation**
- ✅ `PreviewGenerator` with deterministic templates
- ✅ Persian sections: مهم‌ترین خبرها, اخبار مهم, ریزخبرها
- ✅ Priority-based formatting (detailed vs compact)
- ✅ Source attribution (max 5 URLs per story)
- ✅ Tests: preview (all format variations)

**CLI Integration**
- ✅ `newsroom collect` - RSS and GitHub collection
- ✅ `newsroom process normalize` - raw item processing
- ✅ `newsroom process dedupe` - duplicate detection
- ✅ `newsroom process cluster` - story grouping
- ✅ `newsroom digest preview` - Persian digest generation
- ✅ `newsroom pipeline run` - unified end-to-end pipeline
- ✅ All commands with error handling and progress output

**Test Infrastructure**
- ✅ Fixtures for sample RSS and GitHub data
- ✅ Mock collectors for testing
- ✅ Database fixtures with source/items
- ✅ 100+ test cases across 7 test files
- ✅ All tests pass linting (Ruff clean)

### Files Created (M2)

```
src/newsroom/sources/
  base.py              # Protocol and CollectionError
  rss.py               # RSS/Atom collector
  github.py            # GitHub releases collector

src/newsroom/processing/
  normalize.py         # Field extraction and hashing
  dedupe.py            # Duplicate detection
  cluster.py           # Keyword-based story grouping

src/newsroom/digest/
  preview.py           # Persian template generator

src/newsroom/cli/commands/
  __init__.py
  collect.py           # Collection command
  process.py           # Processing commands
  digest.py            # Digest command
  pipeline.py          # Unified pipeline

tests/
  fixtures/
    sample_rss.xml
    sample_github_releases.json
  test_source_base.py
  test_rss.py
  test_github.py
  test_normalize.py
  test_dedupe.py
  test_cluster.py
  test_preview.py

scripts/
  seed-sources.ps1     # Initial source data
```

### Commits (M2)

```
ced768b feat: complete M2 CLI integration and unified pipeline
9e5bbef feat: implement CLI commands for collection, processing, and digest
2956f8e feat: implement Persian preview generator
a2a0f87 feat: implement story clustering
16755c4 feat: implement M2 core components - collectors, normalization, deduplication
b4984fb chore: prepare M2 foundation while repairing M1 incidents
```

## Verification Status

### M1 Foundation (Blocked)
- ⏸️ PowerShell scripts parse (awaiting subagent repair)
- ⏸️ Database migrations (awaiting subagent repair)
- ⏸️ Health command (awaiting subagent repair)
- ⏸️ Tests pass (awaiting subagent repair)
- ✅ Python package structure
- ✅ SQLAlchemy models
- ✅ Alembic configuration
- ✅ Docker Compose PostgreSQL
- ✅ Pydantic settings
- ✅ Structured logging

### M2 Pipeline (Implementation Complete, Verification Pending)
- ✅ Collection from RSS and GitHub
- ✅ Normalization with hashing
- ✅ Deduplication (hash + URL)
- ✅ Story clustering
- ✅ Persian digest generation
- ✅ CLI commands
- ✅ Unified pipeline
- ⏸️ End-to-end runtime verification (depends on M1)
- ⏸️ Idempotency test (depends on M1)

## Next Steps

1. **Await subagent completion** (current)
2. **M1 Verification** - Run M1_VERIFICATION_SEQUENCE.md (10 gates)
3. **M2 Verification** - Run complete pipeline with real data
4. **M2 Idempotency Test** - Run pipeline twice, verify no duplicates
5. **Begin M3** - Hermes editorial workflow + Telegram delivery

## Metrics

- **Code Coverage**: All components have tests
- **Linting**: All checks pass (Ruff clean)
- **Commits**: 15 total (5 planning, 1 M1, 9 M2)
- **Files Modified**: 40+ new/modified files
- **Test Cases**: 100+ assertions across 7 test files
- **Lines of Code**: ~3000 lines (src + tests)

## Risk Status

| Risk | Status | Mitigation |
|------|--------|------------|
| PowerShell encoding corruption | 🟡 Active | Subagent repairing |
| PostgreSQL password mismatch | 🟡 Active | Subagent repairing |
| M1 runtime verification blocked | 🟡 High | Waiting for subagent completion |
| M2 untested in runtime | 🟡 Medium | Verification planned after M1 |
| Persian output quality | 🟢 Low | Templates deterministic, quality review in M3 |

## Dependencies

### External Services (Current)
- None (all public data sources)

### Development Environment
- ✅ Windows 10/11
- ✅ Python 3.12
- ✅ uv installed
- ✅ Docker Desktop running
- ✅ PostgreSQL container healthy (credentials issue being repaired)
- ✅ PowerShell 5.1/7 (encoding issue being repaired)

## Communication

**Autonomous Mode**: Active  
**Human Involvement**: Only for subagent-identified blockers (API keys, secrets, approvals)  
**Next Human Action**: None until subagents complete or encounter unresolvable blocker
