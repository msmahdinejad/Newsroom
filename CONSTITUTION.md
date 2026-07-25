# Newsroom Constitution

## Core Principles

### I. Collection Without AI

Collection must continue when LLMs are unavailable or rate-limited.
- Raw feed ingestion stores items directly to PostgreSQL
- Deduplication uses deterministic algorithms (hashing, URL normalization)
- Event grouping uses time windows and keyword matching
- AI synthesis is a separate stage that operates on collected data

### II. Source Isolation

One failing source cannot break other sources.
- Each source collection runs independently
- Errors are logged per-source
- Failed sources are retried with exponential backoff
- Health status tracked per-source in database

### III. Evidence Preservation

Every claim must trace to source URLs.
- Raw feed items stored before transformation
- Source URLs never discarded
- Digest entries link to original items
- No hallucinated content in output

### IV. Deterministic First

Use deterministic algorithms before probabilistic ones.
- URL normalization for deduplication
- Content hashing for exact duplicates
- Time-window clustering for event grouping
- Title/description similarity only after deterministic passes

### V. Windows-Native Development

Development workflow must work on Windows without WSL.
- PowerShell scripts, not Bash
- Native Python via uv
- Docker Desktop for PostgreSQL only
- Linux deployment path preserved for VPS migration

### VI. No Premature Infrastructure

Start with the simplest stack that works.
- No Redis, Kafka, Elasticsearch, Celery
- No semantic embeddings until deterministic deduplication proven
- No browser automation in MVP

### VII. Test Manually First

Manual execution before scheduling.
- All scripts work standalone
- Clear success/failure output
- Idempotent operations
- Easy to verify results

## Security Constraints

### Secrets Management
- Never commit `.env`, cookies, API keys, session files
- Never print secrets to logs or console
- Use environment variables for credentials
- `.env.example` documents required variables without values

### Git Safety
- Never use `git reset --hard`, `git clean -f`
- Never force push
- Never delete files outside repository
- No destructive database operations in scripts

### Windows Privileges
- No sudo or Administrator elevation required
- Scripts fail gracefully when permissions insufficient
- Document any unavoidable elevation needs

## Development Workflow

### Script Standards
All PowerShell scripts must:
- Set `$ErrorActionPreference = "Stop"`
- Resolve repository root, not assume current directory
- Return non-zero exit code on failure
- Work in both Windows PowerShell 5.1 and PowerShell 7
- Print concise success/failure message
- Never expose secrets in output

### Database Workflow
- PostgreSQL runs in Docker Desktop
- Migrations via Alembic
- Schema changes require migration file
- No direct SQL in application logic

### Testing Strategy
- pytest for all tests
- Test database separate from development database
- Integration tests use real PostgreSQL in Docker
- No mocking of database layer

## Architecture Constraints

### Modular Monolith
- Single Python codebase
- Clear module boundaries
- Each module independently testable
- Avoid circular dependencies

### Data Flow
1. Collection: RSS/Atom/GitHub → PostgreSQL (raw)
2. Normalization: Raw → Normalized items
3. Deduplication: Normalized → Unique items
4. Grouping: Unique items → Event clusters
5. Digest: Event clusters → Persian digest candidates
6. Synthesis: Candidates → Final Persian newsbrief (later)

### Future-Proof
- Support adding Telegram, X, Reddit, YouTube, LinkedIn later
- Preserve ability to run on Linux VPS
- Keep Docker Compose for full containerization
- Structure allows horizontal scaling later

## Governance

This constitution supersedes all other practices.

Amendments require:
- Documentation of rationale
- Update to this file
- Verification that existing code still complies

**Version**: 1.0.0  
**Ratified**: 2026-07-13  
**Last Amended**: 2026-07-13
