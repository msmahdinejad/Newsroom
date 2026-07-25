# Newsroom V2 — Project Report

## 1. What was built
Persian AI/tech newsroom V2: Dockerized pipeline collecting from 37 sources
(26 RSS + 11 GitHub releases), processing through normalization → dedup →
clustering → evidence, generating 3-layer Persian reports, delivering via
Telegram Bot API on 3 daily Tehran schedules.

## 2. Reused vs replaced
**Reused**: RSS/GitHub adapter concepts, feedparser, httpx, SQLAlchemy 2.0,
Alembic, PostgreSQL 16, Docker Compose, PowerShell wrapper concept.

**Replaced**:
- `create_all()` → Alembic migrations (0001 + 0002)
- `str(dict)` raw storage → JSONB
- `eval()` on stored strings → structured dict access
- `str(hash())` (non-deterministic) → SHA-256
- Fake "would deliver" logging → real Bot API via httpx
- `Digest` model → `Report` + `Delivery` models
- No scheduler → APScheduler with Asia/Tehran
- File-based pipeline lock → in-process lock + DB JobRun tracking
- Single `app` container → 6 services (postgres, migrate, collector, report-worker, scheduler, telegram-bot)

## 3. Architecture
```
RSS/GitHub → collect → raw_items (JSONB)
           → normalize → normalized_items (hash, url_hash, canonical_url)
           → dedupe (3-stage: hash → URL → near-dup token Jaccard)
           → cluster (weighted Jaccard, version compounds) → stories + story_items
           → evidence builder → evidence packets (bounded JSONB)
           → PersianEditorial → reports (3-layer Persian)
           → TelegramDelivery → deliveries (chunked, idempotent)
```

Services: postgres, migrate, collector, report-worker, scheduler, telegram-bot

## 4. Docker
- Image: python:3.12-slim, uv, non-root user, health checks
- Compose: 6 services, named network, named volume, loopback-only DB port
- Build: verified (cache + no-cache)
- Restart: `unless-stopped` on all services
- Log rotation: json-file, 5m max, 3 files

## 5. Database
- 13 tables, 2 Alembic migrations
- PostgreSQL 16 on port 55432 (loopback)
- JSONB for structured fields
- Timezone-aware timestamps
- Foreign keys, unique constraints, indexes on hash fields

## 6. Data flow
collect → raw_items → normalize → normalized_items → dedupe → cluster → stories → evidence → reports → deliveries

## 7. Source adapters
- RSSCollector (feedparser + httpx)
- GitHubCollector (GitHub API v3)
- TelegramMTProtoCollector (Telethon, implemented, awaits credentials)

## 8-11. Sources
37 configured, 33 verified collecting, 4 failed (3 RSS URL/parse issues, 1 disabled).
0 Telegram channels (awaits MTProto credentials).

## 12-14. Processing
Normalization: Persian/Arabic char map, URL canonicalization, SHA-256 hashing.
Dedup: exact hash → URL hash → near-duplicate (token Jaccard ≥0.7, 24h window).
Cluster: weighted Jaccard (version compounds double weight), threshold 0.35.
Evidence: bounded packets (story metadata + source list + extracted facts).
Scoring: importance (sources × items), confidence (source count), trust status.

## 15. Security
No secrets in Git/images/logs. JSONB (no eval). Access allowlist. Prompt injection
isolation (evidence packets only, no raw source text to LLM). URL validation.
Content-size limits. Request timeouts. Non-root container.

## 16. Persian editorial
3 layers: مهم‌ترین خبرها (top 3 by importance), اخبار مهم (medium), ریزخبرها (brief).
Trust labels in Persian. Source links preserved. Empty sections omitted.

## 17. Scheduling
APScheduler, Asia/Tehran, 3 jobs: 09:00, 15:00, 21:00. JobRun records in DB.
Hermes cron as secondary trigger (V2 script updated).

## 18. Bot commands
/report, /report new, /report comprehensive, /latest, /help + inline Persian keyboard.
Access control, pipeline lock, subprocess isolation.

## 19. Delivery
Bot API, 4096-char semantic chunking, partial recovery, delivery records with
message IDs, idempotency check.

## 20. Tests
105 passed, 0 failed. Ruff clean.

## 21. Backup/restore
pg_dump verified (8.7MB). Restore into disposable DB verified (37 sources).

## 22. Live evidence
Collection: 33/37 sources, 317+ items. Pipeline: collect→report verified.
Report generated in Persian. Cron path verified.

## 23-26. Limitations
- Telegram delivery: code complete, not live-verified (no bot token)
- MTProto: code complete, blocked on credentials
- LLM editorial: deterministic fallback only, pluggable interface ready
- Agent-Reach: not evaluated
- Docker full-stack restart: postgres verified, all services not yet tested

## 27. Commits
- 32cdd35 feat: V2 rebuild
- 0635c48 test: 105 V2 tests pass
- d6d6a9c fix: V2 cron script

## Readiness assessment
- Development readiness: verified
- Docker readiness: verified (build + no-cache build)
- Database readiness: verified (migrations + backup/restore + restart)
- Source collection readiness: verified (33/37 RSS+GitHub)
- Telegram ingestion readiness: implemented but not verified (blocked)
- Persian report readiness: verified (deterministic renderer)
- Telegram delivery readiness: implemented but not verified (no token)
- Unattended scheduling readiness: implemented but not verified
- Long-term production readiness: operational with limitations
