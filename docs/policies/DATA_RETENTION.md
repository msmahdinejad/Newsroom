# Data Retention Policy

## Retention Periods

### Raw Items
**Retention**: 90 days  
**Rationale**: Original source data for audit, re-processing, debugging  
**Action**: Archive to compressed JSON, then delete from database

### Normalized Items
**Retention**: 180 days  
**Rationale**: Processed data for historical queries, trend analysis  
**Action**: Delete after 180 days, keep aggregates only

### Event Clusters
**Retention**: 365 days  
**Rationale**: Event history for pattern detection, retrospectives  
**Action**: Delete after 1 year, keep metadata (title, date, source count)

### Digest Candidates
**Retention**: Indefinite  
**Rationale**: Published content, small footprint, historical record  
**Action**: Never delete, part of permanent archive

### Logs
**Retention**: 30 days  
**Rationale**: Debugging, audit trail, error investigation  
**Action**: Rotate daily, compress, delete after 30 days

### Source Configuration
**Retention**: Indefinite with history  
**Rationale**: Audit trail of what was monitored when  
**Action**: Soft delete (mark disabled), never hard delete

## Storage Estimates (Daily)

Assumptions:
- 100 sources
- 1000 items/day total
- Average item: 2KB

### Raw Items
- 1000 items × 2KB = 2MB/day
- 90 days = 180MB
- With JSONB compression: ~90MB

### Normalized Items  
- 1000 items × 1KB = 1MB/day
- 180 days = 180MB

### Event Clusters
- ~100 events/day × 500B = 50KB/day
- 365 days = 18MB

### Digest Candidates
- ~100 candidates/day × 2KB = 200KB/day
- Indefinite: ~73MB/year

**Total First Year**: ~90 + 180 + 18 + 73 = ~360MB

## Archival Process

### Monthly Archive Job
1. Export raw_items older than 60 days to gzipped JSON
2. Store in `backups/archive/YYYY-MM/raw_items.json.gz`
3. Verify archive integrity
4. Delete archived rows from database
5. VACUUM database

### Archive Format
```json
{
  "archive_date": "2026-07-13",
  "period": "2026-06-01 to 2026-06-30",
  "item_count": 30000,
  "items": [...]
}
```

## Deletion Procedures

### Automated Deletion
- Scheduled PowerShell script: `scripts/cleanup.ps1`
- Runs weekly
- Deletes by retention policy
- Logs all deletions
- Transaction-safe (rollback on error)

### Manual Deletion
- Requires explicit confirmation
- Must document reason
- Preserve foreign key integrity
- Update STATUS.md with action

## Data Recovery

### From Archive
1. Decompress archive file
2. Parse JSON
3. Re-insert to raw_items with original IDs
4. Re-run normalization pipeline
5. Verify integrity

### Backup Strategy
- Daily PostgreSQL dump to `backups/daily/`
- Keep 7 daily backups
- Weekly backup to `backups/weekly/`
- Keep 4 weekly backups
- Monthly backup to `backups/monthly/`
- Keep 12 monthly backups

## Privacy Considerations

MVP has no user data, only public content.

Future considerations when adding authenticated sources:
- User credentials: Never log, delete immediately after use
- Session tokens: Delete after session ends
- API keys: Store encrypted, delete when source removed
- Personal data from sources: Same retention as content

## Compliance

Current scope (public data only):
- No GDPR requirements (no personal data collected)
- No CCPA requirements (no California users)
- Iranian data protection: Public content, no restrictions

Future scope (authenticated sources):
- GDPR compliance if processing EU data
- Right to deletion for user credentials
- Data portability for configuration

## Audit Trail

Changes to retention policy:
- Document reason in `docs/adr/`
- Update this file
- Migration plan if affects existing data
- Announce change in STATUS.md
