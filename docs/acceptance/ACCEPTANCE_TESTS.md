# Acceptance Tests

## Test Environment

- Windows 10/11 native
- Fresh clone of repository
- Docker Desktop running
- Python 3.12 + uv installed
- PowerShell 5.1 or 7

## Pre-Test Setup

```powershell
# Clone and setup
git clone <repo-url> newsroom
cd newsroom
.\scripts\setup.ps1
```

Expected: Setup completes without errors, database running, migrations applied.

---

## AT-001: Database Lifecycle

**Objective**: Verify database can be started, migrated, and stopped cleanly.

**Steps**:
1. Run `.\scripts\db-up.ps1`
2. Verify PostgreSQL container running: `docker ps`
3. Run `.\scripts\migrate.ps1`
4. Connect to database and verify tables exist
5. Run `.\scripts\db-down.ps1`
6. Verify container stopped: `docker ps`

**Expected Results**:
- ✅ Container starts on port 5432
- ✅ Migrations apply successfully
- ✅ All 6 tables created: sources, raw_items, normalized_items, event_clusters, cluster_items, digest_candidates
- ✅ Container stops cleanly

**Actual Results**: [To be filled during test]

---

## AT-002: Source Validation

**Objective**: Verify can test sources without storing data.

**Steps**:
1. Edit config to add test RSS feed: https://hnrss.org/newest
2. Run `.\scripts\validate-sources.ps1`
3. Check output for success/failure per source

**Expected Results**:
- ✅ Connects to RSS feed
- ✅ Parses feed successfully
- ✅ Reports item count
- ✅ No data stored in database
- ✅ Exit code 0 if all sources valid

**Actual Results**: [To be filled during test]

---

## AT-003: RSS Collection

**Objective**: Collect from real RSS feeds and store raw items.

**Steps**:
1. Add 5 RSS feeds to sources table
2. Run `.\scripts\collect.ps1`
3. Query raw_items table
4. Verify one source fails gracefully (use invalid URL)

**Expected Results**:
- ✅ At least 10 items collected total
- ✅ raw_data JSONB populated
- ✅ collected_at timestamps set
- ✅ Failed source logged but doesn't stop others
- ✅ Failed source marked with health_status='degraded'

**Actual Results**: [To be filled during test]

---

## AT-004: GitHub Collection

**Objective**: Collect GitHub releases.

**Steps**:
1. Add 3 GitHub repos to sources: python/cpython, pytorch/pytorch, microsoft/typescript
2. Run `.\scripts\collect.ps1`
3. Query raw_items for GitHub sources
4. Verify release data structure

**Expected Results**:
- ✅ Latest releases fetched
- ✅ Release data includes tag_name, published_at, body
- ✅ Stored as JSONB in raw_data
- ✅ Rate limits respected (check logs)

**Actual Results**: [To be filled during test]

---

## AT-005: Normalization

**Objective**: Transform raw items to standard schema.

**Steps**:
1. Ensure raw_items exist from AT-003 and AT-004
2. Run `.\scripts\process.ps1` (or specific normalize command)
3. Query normalized_items table
4. Verify content_hash and url_normalized populated

**Expected Results**:
- ✅ All raw items normalized
- ✅ title, description, source_url extracted
- ✅ content_hash is 64-char hex string
- ✅ url_normalized has tracking params removed
- ✅ published_at parsed correctly

**Actual Results**: [To be filled during test]

---

## AT-006: Deduplication

**Objective**: Detect exact duplicates and URL variants.

**Steps**:
1. Manually insert duplicate raw items (same content)
2. Normalize them
3. Run deduplication
4. Query for items with is_duplicate=TRUE

**Expected Results**:
- ✅ Identical content hashes marked as duplicates
- ✅ URL variants detected (example.com?utm vs example.com)
- ✅ duplicate_of_id points to original
- ✅ No false positives (different content not marked duplicate)

**Actual Results**: [To be filled during test]

---

## AT-007: Event Clustering

**Objective**: Group items about same event.

**Test Data**: Manually create 5 items about "Python 3.13 release" and 3 about "PyTorch 2.0 release"

**Steps**:
1. Insert test normalized_items with known event keywords
2. Run clustering
3. Query event_clusters and cluster_items

**Expected Results**:
- ✅ 2 clusters created
- ✅ "Python 3.13" items in one cluster (5 items)
- ✅ "PyTorch 2.0" items in separate cluster (3 items)
- ✅ Keywords extracted correctly
- ✅ Time windows respected (items >24h apart not clustered)

**Actual Results**: [To be filled during test]

---

## AT-008: Persian Digest Generation

**Objective**: Create Persian digest candidates with source links.

**Steps**:
1. Ensure event_clusters exist from AT-007
2. Run digest generation
3. Query digest_candidates table
4. Verify Persian text quality with native speaker

**Expected Results**:
- ✅ headline_fa is readable Persian
- ✅ summary_fa describes event in Persian
- ✅ source_urls array populated
- ✅ All source URLs valid and reachable
- ✅ Priority assigned (high/medium/low)
- ✅ Section assigned (main/micro)

**Actual Results**: [To be filled during test]  
**Native Speaker Review**: [To be filled]

---

## AT-009: End-to-End Pipeline

**Objective**: Run complete pipeline from collection to digest.

**Steps**:
1. Start with empty database (run reset-test-data.ps1)
2. Configure 10 real sources (5 RSS, 5 GitHub)
3. Run `.\scripts\run-all.ps1`
4. Measure execution time
5. Verify output at each stage

**Expected Results**:
- ✅ Completes in <5 minutes for ~100 items
- ✅ No errors in logs
- ✅ At least 10 digest candidates created
- ✅ All candidates have source attribution
- ✅ Database transactions consistent (no orphaned records)

**Actual Results**: [To be filled during test]  
**Execution Time**: [To be filled]

---

## AT-010: Error Handling

**Objective**: Verify graceful error handling.

**Steps**:
1. Add invalid RSS URL (404, timeout, malformed XML)
2. Add private GitHub repo (403)
3. Run collection
4. Verify other sources continue

**Expected Results**:
- ✅ Errors logged clearly
- ✅ health_status updated to 'failing'
- ✅ consecutive_failures incremented
- ✅ Other sources unaffected
- ✅ Exit code non-zero but process completes

**Actual Results**: [To be filled during test]

---

## AT-011: Source Isolation

**Objective**: Verify failed source doesn't break others.

**Steps**:
1. Configure 5 sources, make 1 deliberately fail (invalid URL)
2. Run collection
3. Verify 4 sources collected successfully
4. Check failed source in database

**Expected Results**:
- ✅ 4 sources have raw_items
- ✅ 1 source has error in last_error column
- ✅ Failed source retried with backoff
- ✅ Total items collected from working sources

**Actual Results**: [To be filled during test]

---

## AT-012: Secret Safety

**Objective**: Verify no secrets exposed in logs or output.

**Steps**:
1. Add source with API key in URL
2. Run collection
3. Review all logs
4. Review database content

**Expected Results**:
- ✅ API keys not in logs
- ✅ Sensitive URLs sanitized in output
- ✅ No secrets in error messages
- ✅ .env not committed to git

**Actual Results**: [To be filled during test]

---

## AT-013: Developer Workflow

**Objective**: Verify all PowerShell scripts work correctly.

**Scripts to Test**:
- ✅ setup.ps1 - Initial setup
- ✅ db-up.ps1 - Start database
- ✅ db-down.ps1 - Stop database
- ✅ migrate.ps1 - Run migrations
- ✅ validate-sources.ps1 - Test sources
- ✅ collect.ps1 - Collect data
- ✅ process.ps1 - Process pipeline
- ✅ digest.ps1 - Generate digests
- ✅ run-all.ps1 - Full pipeline
- ✅ health.ps1 - System health check
- ✅ test.ps1 - Run tests
- ✅ lint.ps1 - Run linters
- ✅ logs.ps1 - View logs
- ✅ reset-test-data.ps1 - Reset database

**Expected Results**:
- All scripts return 0 on success, non-zero on failure
- Clear success/failure messages
- No errors on fresh Windows install
- Scripts resolve repo root correctly

**Actual Results**: [To be filled during test]

---

## AT-014: Testing Infrastructure

**Objective**: Verify test suite runs successfully.

**Steps**:
1. Run `.\scripts\test.ps1`
2. Check coverage report
3. Verify test database separate from dev

**Expected Results**:
- ✅ All tests pass
- ✅ Coverage >80%
- ✅ Tests complete in <2 minutes
- ✅ No network calls in unit tests
- ✅ Can run tests repeatedly without cleanup

**Actual Results**: [To be filled during test]  
**Coverage**: [To be filled]

---

## AT-015: Data Retention

**Objective**: Verify retention policy enforcement (manual simulation).

**Steps**:
1. Create old raw_items (backdated to 91 days ago)
2. Run retention cleanup (manual trigger)
3. Verify old items deleted, recent preserved

**Expected Results**:
- ✅ Items >90 days deleted from raw_items
- ✅ Items <90 days preserved
- ✅ Foreign key integrity maintained
- ✅ Digest candidates never deleted

**Actual Results**: [To be filled during test]

---

## Pass Criteria

MVP is acceptable if:
- [ ] All 15 acceptance tests pass
- [ ] No critical security issues
- [ ] Performance targets met (<5 min pipeline)
- [ ] All PowerShell scripts work on fresh Windows install
- [ ] Persian output reviewed by native speaker
- [ ] Source attribution preserved throughout
- [ ] Documentation complete

## Test Execution Log

| Test ID | Date Tested | Tester | Result | Notes |
|---------|-------------|--------|--------|-------|
| AT-001 | | | | |
| AT-002 | | | | |
| AT-003 | | | | |
| AT-004 | | | | |
| AT-005 | | | | |
| AT-006 | | | | |
| AT-007 | | | | |
| AT-008 | | | | |
| AT-009 | | | | |
| AT-010 | | | | |
| AT-011 | | | | |
| AT-012 | | | | |
| AT-013 | | | | |
| AT-014 | | | | |
| AT-015 | | | | |
