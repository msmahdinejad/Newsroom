# Gate 7 Requirements Audit

This ledger is the persistent source of truth for Gate 7. Initial status is
based only on evidence reproduced from the starting commit
`10a0e2d3933e3ca4f1d0374c5119f119c6b70c05`; earlier gate reports are context,
not proof. Protected local values are represented only by safe labels.

Initial baseline: **7 PASS, 7 FAIL, 22 PARTIAL**.

| ID | Requirement | Initial | Current evidence | Corrective action | Final evidence | Final |
|---|---|---:|---|---|---|---:|
| R01 | Correct Gate 7 branch, start commit, and clean tree | PASS | Branch `gate-7-final-audit`, exact starting commit, clean tree | None | Pending final audit | PENDING |
| R02 | Maintainable package architecture and boundaries | PARTIAL | Clear modules exist; independent cleanup not complete | Audit code smells, obsolete gate paths, interfaces | Pending | PENDING |
| R03 | Reproducible Python dependencies and frozen lock | PARTIAL | `uv lock --check` passes; 75 locked packages on Python 3.12 | Frozen clean-clone sync and dependency/license audit | Pending | PENDING |
| R04 | PostgreSQL schema, constraints, indexes, migrations | PARTIAL | Added fingerprint-only Telegram audit migration `0011`; empty-to-`0010` plus legacy rows to head passed 7 schema tests | Upgrade current production and repeat empty/current verification | Pending | PENDING |
| R05 | Production Compose stack and health checks | PASS | Seven required services independently observed running healthy | Rebuild and final restart | Pending | PENDING |
| R06 | Authoritative workbook has exactly 1344 represented rows | PASS | Artifact-tool read: `All Sources!A1:T1345`, 1344 data rows/IDs; PostgreSQL has zero missing or extra workbook IDs and zero mapped-field mismatches | Final status snapshot | Pending | PENDING |
| R07 | Workbook metadata, stable identity, duplicates, idempotent import | PARTIAL | Production has 1344 rows, 4 classified duplicates, and zero metadata/stable-identity mismatches; two repeated imports each upserted 1344 without count/state change | Portable explicit workbook path and final integration tests | Pending | PENDING |
| R08 | Every active source has a bounded real attempt | PASS | 1236 active inventory rows; zero linked active sources without `last_attempt_at` | Repeat bounded validation after remediation | Pending | PENDING |
| R09 | Every inactive source has a specific reason | PASS | 104 inactive + 4 duplicate rows; zero missing reasons | Verify classifications after final sweep | Pending | PENDING |
| R10 | Telegram MTProto real ingestion and cursor continuity | PASS | Preserved session authenticated through SOCKS5; 149 healthy channels | Restart and soak reproduction | Pending | PENDING |
| R11 | X timeline real ingestion and cursor continuity | PARTIAL | Production state exists; Gate 7 live reproduction pending | Run bounded real read and restart/dedup checks | Pending | PENDING |
| R12 | Agent-Reach pinned, licensed, healthy, bounded | PARTIAL | Pinned revision configured and service healthy | Verify package/revision, doctor, live read, notices | Pending | PENDING |
| R13 | RSS and Atom live collection | PARTIAL | Adapter and tests exist | Representative live read, cursor and dedup evidence | Pending | PENDING |
| R14 | Safe website and newsletter live collection | PARTIAL | Adapter and validation paths exist | Representative live reads and failure isolation | Pending | PENDING |
| R15 | GitHub repository/release live collection | PARTIAL | Native adapter and tests exist | Representative live read, cursor and dedup evidence | Pending | PENDING |
| R16 | YouTube channel live collection | PARTIAL | RSS adapter and tests exist | Representative live read and handle-resolution evidence | Pending | PENDING |
| R17 | Reddit, forum, and community live collection | PARTIAL | Native/Agent-Reach paths exist | Representative live reads and isolation evidence | Pending | PENDING |
| R18 | Normalize, deduplicate, cluster, rank, and evidence lineage | PARTIAL | Gate 7 AI report 473 exposed missing Evidence rows for selected comprehensive stories; corrective runner work is active | Persist selected-story evidence, regenerate, trace complete lineage, run regression | Pending | PENDING |
| R19 | Persistent router queue, quota, rotation, cooldown, fallback | PARTIAL | 185 focused router/editorial tests and fresh five-call Gemini report passed; independent persistence/fallback audit is active | Complete live rotation/fallback/recovery and PostgreSQL verification | Pending | PENDING |
| R20 | Every non-empty LLM access value and enabled model validated live | PARTIAL | Safe counts discovered for Gemini, Mistral, Groq, and NVIDIA; final per-value bounded revalidation is active | Record every safe-labeled result and exact enabled matrix | Pending | PENDING |
| R21 | Persian editorial quality, grounding, hierarchy, lineage | PARTIAL | Fresh non-fallback Persian AI report 473 delivered as message 63, but incomplete evidence lineage correctly blocks acceptance | Fix lineage and produce a new fully traced report | Pending | PENDING |
| R22 | Tehran schedule and delivery-boundary correctness | PARTIAL | Scheduler service healthy | Deterministic clock and production-state reproduction | Pending | PENDING |
| R23 | All owner Telegram commands correct and idempotent | PARTIAL | Fixed raw identity persistence and permanent manual-command reuse; update-scoped keys plus ten-minute cooldown are covered in a 72-test Telegram suite | Apply migration, restart, and perform bounded live command verification | Pending | PENDING |
| R24 | Full-stack restart recovery | PARTIAL | Individual Gate 6 restart evidence exists | Restart complete stack and verify all durable state | Pending | PENDING |
| R25 | Bounded production-style soak without growth/leaks | PARTIAL | Soak tooling exists | Run soak and inspect locks/jobs/queues/resources | Pending | PENDING |
| R26 | Service access isolation and protected-value safety | PARTIAL | Removed provider mount from processing worker and unused Telegram access from scheduler; exact-value audit found legacy Telegram IDs in DB/history and an old proxy endpoint in ingestor logs | Apply privacy migration, recreate services/logs, rewrite public history from private bundle, rerun exact audit | Pending | PENDING |
| R27 | Remove obsolete workarounds, temporary code, stale markers | FAIL | Numerous gate-specific scripts/docs and stale public surface | Review, remove/archive only when safe, fix code defects | Pending | PENDING |
| R28 | Professional open-source root/governance files | FAIL | Required root/governance files and safe provider template are now present in the working tree; independent review is active | Validate content, packaging, build context, and links | Pending | PENDING |
| R29 | GitHub templates, Dependabot, and practical CI | FAIL | Issue/PR templates, Dependabot, and CI are now present in the working tree | Execute equivalent local jobs and inspect workflow safety | Pending | PENDING |
| R30 | Isolated clean-clone reproducibility | FAIL | Not demonstrated from starting commit | Reproduce install/migrate/tests/Compose/dev startup | Pending | PENDING |
| R31 | Dependency and third-party license notices | FAIL | No complete third-party notices | Audit direct/pinned tools and add notices | Pending | PENDING |
| R32 | Required final architecture/runbook/audit documentation | FAIL | Final architecture, production runbook, provider setup, release, source, and workstream audit documents are being created from reproduced evidence | Finish live/restart/test/release evidence documents and cross-check commands | Pending | PENDING |
| R33 | Semantic release notes, version, and local tag | FAIL | No Gate 7 release candidate/tag | Recommend version, document upgrade, create local tag | Pending | PENDING |
| R34 | Required production services currently healthy | PASS | PostgreSQL, collectors, workers, scheduler, bot, ingestor all healthy | Preserve through final rebuild/restart | Pending | PENDING |
| R35 | Public-release history contains no protected material | PARTIAL | Exact-value scanner reports one current machine path, legacy Telegram IDs and machine paths in Git history, one old proxy log match, and two raw-ID DB matches without exposing values | Sanitize tracked path, create private bundle, rewrite public history, migrate DB, recreate logs, rerun for zero | Pending | PENDING |
| R36 | Complete deterministic, PostgreSQL, live, build verification | PARTIAL | Earlier gate results exist but are not accepted as Gate 7 proof | Run complete suite on production-safe and fresh DBs | Pending | PENDING |
