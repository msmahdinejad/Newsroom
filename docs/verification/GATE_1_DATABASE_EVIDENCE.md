# Gate 1 — Database Evidence

## Migration

**Command**: `uv run alembic upgrade head` (inside migrate container)
**Exit code**: 0
**Version**: `0002_v2_stories_reports` (head)

## Tables (14 total)

```
alembic_version, sources, source_credentials, collection_cursors,
collection_runs, raw_items, normalized_items, stories, story_items,
evidence, reports, deliveries, job_runs, processing_errors,
apscheduler_jobs (created by SQLAlchemyJobStore)
```

## Row counts (post Gate 1 verification)

| Table | Count |
|---|---|
| sources | 39 |
| raw_items | 600 |
| reports | 4+ |
| collection_cursors | 36 |
| apscheduler_jobs | 3 |
| job_runs | 1+ |

## Alembic current/head consistency

**Command**: `alembic current` → `0002_v2_stories_reports`
**Command**: `alembic heads` → `0002_v2_stories_reports`
**Result**: Consistent

## Backup

**Command**: `docker exec newsroom-postgres pg_dump -U newsroom -d newsroom`
**Size**: 7,161,441 bytes (~6.8 MB)
**Timestamp**: 2026-07-16T11:53:53

## Restore (disposable database)

**Command**: `createdb newsroom_restore_test && psql -d newsroom_restore_test < backup.sql`
**Result**: All row counts match original

| Table | Original | Restored |
|---|---|---|
| sources | 39 | 39 |
| raw_items | 600 | 600 |
| reports | 4 | 4 |
| collection_cursors | 36 | 36 |
| apscheduler_jobs | 3 | 3 |

Disposable database dropped after verification.
