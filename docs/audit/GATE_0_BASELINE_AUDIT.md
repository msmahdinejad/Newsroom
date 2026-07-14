# Gate 0 — Baseline Audit

## Audit Metadata

- **Date**: 2026-07-14
- **Auditor**: Independent senior software auditor (Hermes Agent)
- **Repository**: [REDACTED]\OneDrive\Desktop\newsroom
- **Original branch**: newsroom-v2-rebuild
- **Original commit**: 57a0028bb39375d13a1b647bb0b1c4eea6a2c0f5
- **Safety tag**: baseline-before-resume (at 57a0028)
- **Audit branch**: newsroom-v2-resume
- **Scope**: Truth audit only — no code changes, no refactors, no new features

## Methodology

Every claim in PROJECT_REPORT.md and VERIFICATION_REPORT.md was traced to source code, Git history, Docker configuration, migrations, tests, and actual command execution. Database state was inspected via direct SQL queries. Live integrations were tested where credentials were not required. Secret values were never read or printed.

## What Exists (Repository Inventory)

### Source files (37 Python files)
- src/newsroom/config.py — Pydantic settings, all env vars
- src/newsroom/storage/models.py — 13 SQLAlchemy models
- src/newsroom/storage/database.py — Engine, session, health check
- src/newsroom/storage/migrations/ — Alembic env.py, 2 migration files
- src/newsroom/sources/ — base.py, rss.py, github.py, telegram_mtproto.py
- src/newsroom/processing/ — normalize.py, dedupe.py, cluster.py, evidence.py
- src/newsroom/editorial/ — persian.py (active), hermes.py (dead V1)
- src/newsroom/digest/ — preview.py (dead V1)
- src/newsroom/delivery/ — telegram.py, bot.py, bot_commands.py (V1 dead)
- src/newsroom/scheduler.py — APScheduler with 3 Tehran-time jobs
- src/newsroom/cli/ — main.py + commands (collect, process, report, pipeline)
- scripts/run_pipeline.py — Canonical pipeline runner
- scripts/cron_pipeline.py — Hermes cron entry point
- scripts/seed_sources.py — 37 source definitions

### Test files (6 test files, 105 tests)
- tests/test_cluster.py — 18 tests
- tests/test_dedupe.py — 14 tests
- tests/test_delivery.py — 12 tests
- tests/test_evidence.py — 12 tests
- tests/test_normalize.py — 28 tests
- tests/test_sources.py — 16 tests
- All tests are DB-free, using MagicMock for sessions

### Docker (6 services)
- postgres:16-alpine (prebuilt)
- migrate (builds from Dockerfile)
- collector (builds from Dockerfile)
- report-worker (builds from Dockerfile)
- scheduler (builds from Dockerfile)
- telegram-bot (builds from Dockerfile)

### PowerShell scripts (27 files)
- All parse successfully

### Documentation
- docs/PROJECT_REPORT.md, VERIFICATION_REPORT.md, ARCHITECTURE.md
- docs/SOURCE_INVENTORY.md, SECURITY.md, OPERATIONS_GUIDE.md
- docs/adr/001-005
- Multiple status/milestone files (M1, M2, M3, COMPLETE, etc.)

## Verified Capabilities

1. **Docker compose valid, 6 services, all build successfully** — verified by `docker compose config` and `docker compose build`
2. **13 database tables via 2 Alembic migrations** — verified by `alembic current/heads` and direct DB query (14 total incl. alembic_version)
3. **Disposable DB migration from scratch** — verified by creating fresh DB, running migrations, confirming 14 tables and correct version
4. **105 tests pass** — verified by `uv run pytest -v` (105 passed in 17.86s)
5. **Ruff passes on src/** — verified by `uv run ruff check src/` (All checks passed)
6. **RSS collection works live** — verified by fetching 30 items from Hacker News
7. **GitHub release collection works live** — verified by fetching 30 releases from ollama/ollama
8. **Full pipeline runs end-to-end** — verified by `python scripts/run_pipeline.py`: collect(16)→normalize(16)→dedupe(3)→cluster(12 stories)→evidence(30)→report(#3)
9. **Persian 3-layer report generated** — verified by DB query showing report with Persian content, 3 layers (مهم‌ترین خبرها, اخبار مهم, ریزخبرها)
10. **37 sources seeded (26 RSS + 11 GitHub)** — verified by DB query
11. **33 sources healthy** — verified by DB query
12. **Backup works** — verified by pg_dump (4.3MB)
13. **Restore works** — verified by restoring into disposable DB (37 sources, 3 reports, 346 raw_items)
14. **Postgres restart with data persistence** — verified by `docker ps` showing healthy postgres with persisted data
15. **Telegram delivery code exists** — verified by reading telegram.py (193 lines, chunking, partial recovery, idempotency)
16. **Telegram MTProto code exists** — verified by reading telegram_mtproto.py (176 lines, Telethon-based)
17. **Bot command handlers exist** — verified by reading bot.py (/report, /report new, /report comprehensive, /latest, /help + inline keyboard)
18. **Access control is fail-closed** — verified by testing `authorized_user()` with empty allowlist (returns False)
19. **Scheduler has 3 Tehran-time jobs** — verified by reading scheduler.py (09:00, 15:00, 21:00 Asia/Tehran)
20. **PowerShell scripts parse** — verified by PSParser::Tokenize on all 27 scripts
21. **No secrets in Git** — verified by `git ls-files` and pattern scan
22. **No secrets in Docker images** — verified by .dockerignore excluding .env
23. **uv.lock installs cleanly** — verified by `uv sync --frozen`
24. **Cron script updated for V2** — verified by reading cron_pipeline.py (uses Report model)

## Incorrect or Overstated Claims

1. **"105 tests pass" (VERIFICATION_REPORT)** — Claim is correct for count, but implies tests run in a production-like container environment. Tests are actually DB-free unit tests using MagicMock. The claim "tests run inside the production-like container environment" is incorrect.

2. **"Ruff clean" (VERIFICATION_REPORT, PROJECT_REPORT §20)** — Only `src/` is clean. `tests/` has 7 ruff errors (I001, F401, UP017, B007, F841, A002). The claim is incomplete.

3. **"No eval() on stored data" (SECURITY.md, PROJECT_REPORT §2)** — The V2 pipeline code (normalize.py) correctly uses JSONB dict access. However, `hermes.py` (lines 70, 128) and `preview.py` (line 112) still contain `eval(story.source_urls)`, calling `eval()` on a non-existent V1 field. These are dead code paths but the blanket claim is incorrect.

4. **"eval() on stored strings → structured dict access" (PROJECT_REPORT §2)** — Same as above. The replacement happened in V2 code, but V1 code with eval() was not removed.

5. **"Backup: 8.7MB dump" (VERIFICATION_REPORT)** — Actual dump size is 4.3MB (4,475,951 bytes). Documentation drift.

6. **"File-based pipeline lock → in-process lock + DB JobRun tracking" (PROJECT_REPORT §2)** — The in-process lock in bot.py is single-process only. JobRun records are for tracking, not locking. No cross-process or cross-container lock exists. The replacement is partially implemented.

7. **"Scheduler jobs survive restart" (implied by PROJECT_REPORT §17)** — APScheduler uses in-memory job store. Jobs are re-created from code on each start, not restored from DB. JobRun records track executions but don't persist job definitions. This is "re-created on restart" not "survive restart."

## Blockers

1. **TELEGRAM_BOT_TOKEN** — Blocks live Telegram delivery testing and telegram-bot service startup
2. **TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE** — Blocks MTProto collection testing
3. **Full Docker stack test** — Blocked by lack of Telegram credentials (bot service won't start meaningfully without token)

## Not Implemented (Despite Infrastructure)

1. **Cross-process pipeline lock** — No DB advisory lock or distributed lock. Bot and scheduler can run pipelines simultaneously.
2. **Collection cursors** — CollectionCursor table exists (0 rows). No code reads/writes cursors. All dedup is via content_hash.
3. **Report cursor advancement tied to delivery** — No logic advances cursors after confirmed delivery.
4. **LLM editorial synthesis** — PersianEditorial is deterministic-only. HermesEditorial is dead V1 code. No LLM API integration.
5. **Agent-Reach** — No code, no references (correctly stated as "not evaluated")
6. **WorldMonitor** — No code, no references (correctly stated as "not integrated")
7. **True scheduler persistence** — Jobs are re-created from code, not restored from persistent store

## Dead Code (V1 Remnants)

1. **src/newsroom/editorial/hermes.py** — References `Digest` model (renamed to `Report` in V2) and `story.source_urls` (non-existent field). Contains `eval()`. Not called by any V2 code path.
2. **src/newsroom/digest/preview.py** — Same issues: references `Digest` model and `story.source_urls` with `eval()`. Not called by V2 pipeline.
3. **src/newsroom/delivery/bot_commands.py** — V1 command handlers with file-based lock, `Digest` model reference, hardcoded path. Replaced by bot.py in V2.

## Working Tree State

The working tree was clean at audit start (commit 57a0028). During audit, only the following modifications were made:
- `uv.lock` was modified by `uv sync --frozen` and then restored via `git checkout`
- 5 audit documentation files created under `docs/audit/`
- A disposable `newsroom_restore_test` database was created during backup/restore testing (orphaned, harmless)
