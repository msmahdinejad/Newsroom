# Gate 0 — Command Evidence

All commands executed during the audit. Outputs recorded without secrets.

## Git

### git status
```
On branch newsroom-v2-resume
nothing to commit, working tree clean
```

### git log --oneline --decorate -n 20
```
57a0028 (HEAD -> newsroom-v2-rebuild) docs: ARCHITECTURE, SOURCE_INVENTORY, OPERATIONS_GUIDE, VERIFICATION_REPORT, SECURITY
af694ce docs: PROJECT_REPORT, ADRs 004/005, V2 cron script
d6d6a9c fix: V2 cron script replaces Digest-dependent Hermes pipeline
0635c48 test: 105 V2 tests pass, lint clean, MTProto collector, backup/restore
32cdd35 feat: V2 rebuild — data model, migrations, pipeline, editorial, delivery, scheduler
9cc1b96 (tag: checkpoint-v1-before-rebuild, main) fix: final lint cleanup on seed_sources
```

### Safety tag and branch
```
git tag baseline-before-resume  -> created at 57a0028
git checkout -b newsroom-v2-resume -> switched
```

## Docker

### docker compose config --quiet
```
exit 0 (valid)
```

### docker compose config (service list)
```
Services: postgres, migrate, collector, report-worker, scheduler, telegram-bot (6)
```

### docker compose build
```
exit 0 — all 5 buildable services built (postgres is prebuilt image)
Images: newsroom-migrate, newsroom-collector, newsroom-report-worker, newsroom-scheduler, newsroom-telegram-bot
```

### docker ps (existing containers)
```
newsroom-postgres: Up 2 hours (healthy)
newsroom-migrate: Exited (0) 2 hours ago
```

## Migrations

### alembic current
```
0002_v2_stories_reports (head)
```

### alembic heads
```
0002_v2_stories_reports
```

### Disposable DB migration
```
CREATE DATABASE newsroom_audit;
alembic upgrade head -> 0001_v2_schema, then 0002_v2_stories_reports
Table count: 14 (13 app + alembic_version)
alembic_version: 0002_v2_stories_reports
DROP DATABASE newsroom_audit;
```

### Tables in production DB
```
alembic_version, collection_cursors, collection_runs, deliveries, evidence,
job_runs, normalized_items, processing_errors, raw_items, reports,
source_credentials, sources, stories, story_items
Total: 14 (13 application tables + 1 alembic_version)
```

### DB row counts
```
sources: 37
raw_items: 330+ (grows with each pipeline run)
reports: 3 (after audit pipeline run)
deliveries: 0
job_runs: 0
collection_cursors: 0
```

## Tests

### uv run pytest -v
```
105 passed in 17.86s
test_cluster.py: 18 tests
test_dedupe.py: 14 tests
test_delivery.py: 12 tests
test_evidence.py: 12 tests
test_normalize.py: 28 tests
test_sources.py: 16 tests
Test type: DB-free, MagicMock for all DB sessions
```

### uv run ruff check src/
```
All checks passed! exit 0
```

### uv run ruff check tests/
```
7 errors (I001, F401, UP017, B007, F841, A002) — tests NOT clean
```

### uv run mypy src/
```
15 errors in 6 files (checked 37 source files)
Key errors:
- hermes.py: Module has no attribute "Digest", Story has no attribute "source_urls"
- preview.py: Module has no attribute "Digest", Story has no attribute "source_urls"
- telegram_mtproto.py: None has no attribute "start"/"iter_messages"/"get_entity"
- rss.py: datetime gets multiple values for keyword argument "tzinfo"
- telegram.py: Returning Any from function declared to return "int"
- persian.py: Incompatible types in assignment
```

## Live Collection

### RSS (Hacker News)
```
RSS_LIVE: collected 30 items from Hacker News
Sample: "Codex starts encrypting sub-agent prompts"
```

### GitHub (ollama/ollama)
```
GITHUB_LIVE: collected 30 releases from ollama/ollama
Sample: tag=v0.32.0, name=v0.32.0
```

## Pipeline Run

### uv run python scripts/run_pipeline.py
```
database: ok
collect: 36 sources found, 4 errors, 16 items collected
  - Vercel Blog: Parse failed
  - rust-lang/rust: HTTP error
  - Anthropic Blog: HTTP 404
  - AI Snake Oil: Feed too large (1.3MB)
normalize: 16 items normalized
dedupe: 3 duplicates marked (3 url_match)
cluster: 12 stories created, 13 items clustered
evidence: 30 packets built
report: report #3 generated
deliver: skipped (Telegram not configured)
status: ok
```

## Source Health
```
33 healthy, 3 degraded (Vercel, Anthropic, AI Snake Oil), 1 unavailable (Meta AI Blog - disabled)
```

## Backup/Restore

### pg_dump
```
Dump size: 4,475,951 bytes (~4.3MB)
```

### Restore verification
```
CREATE DATABASE newsroom_restore_test;
pg_dump | psql -> success
sources: 37, reports: 3, raw_items: 346
```

## PowerShell Scripts

### Parser validation (27 scripts)
```
All 27 .ps1 files: OK (parsed successfully)
```

## Secret Scanning

### .env in git
```
git ls-files .env -> not tracked
git log --all -- .env -> no commits
```

### Pattern scan
```
No secrets (sk-, ghp_, xox, AKIA) found in tracked files
```

## uv sync

### uv sync --frozen
```
exit 0 — dependencies install cleanly from lock file
```
