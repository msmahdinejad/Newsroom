# Persian AI Newsroom - M1 Complete (with blocker)

## What Was Simplified

Reduced 11 milestones (112 tasks, 6 weeks) to 3 milestones (29 tasks, ~2 weeks):

- **M1: Local Foundation** (12 tasks) - Python, PostgreSQL, scripts, health
- **M2: First Complete Pipeline** (12 tasks) - RSS/GitHub → Persian preview
- **M3: Hermes Editorial & Telegram** (5 tasks) - Synthesis and delivery
- **M4: Future** - Deferred (Telegram auth, Agent-Reach, YouTube, etc.)

Removed: administrative tasks, stakeholder reviews, role assignments, separate normalization/deduplication/clustering milestones.

## What Was Implemented (M1)

### Core Infrastructure
- Python 3.12 package managed by uv
- SQLAlchemy 2 models: `Source`, `RawItem`, `NormalizedItem`, `Story`, `Digest`
- Alembic migrations (configured, pending DB access)
- PostgreSQL 16 in Docker Compose
- Pydantic-settings configuration with `.env` loading
- Structured JSON logging

### CLI Commands
```bash
newsroom health          # Check database connection and tables
newsroom db migrate      # Run Alembic migrations
```

### PowerShell Scripts
```powershell
.\scripts\setup.ps1              # Full environment setup
.\scripts\db-up.ps1              # Start PostgreSQL
.\scripts\db-down.ps1            # Stop PostgreSQL
.\scripts\migrate.ps1            # Run migrations
.\scripts\health.ps1             # Health check
.\scripts\lint.ps1               # Ruff + mypy
.\scripts\test.ps1               # pytest
.\scripts\collect.ps1            # (M2 stub)
.\scripts\process.ps1            # (M2 stub)
.\scripts\digest.ps1             # (M2 stub)
.\scripts\validate-sources.ps1  # (M2 stub)
```

### Test Infrastructure
- pytest with session-scoped database fixture
- Test for Source model creation
- (Blocked by DB password issue)

## Known Blocker

Docker volume `newsroom_postgres_data` has mismatched credentials from prior initialization.

**Manual fix required:**

```powershell
# In project directory
cd [REDACTED]\OneDrive\Desktop\newsroom

# Stop and remove volume (DELETES ALL DATA)
docker compose down
docker volume rm newsroom_postgres_data

# Start fresh
docker compose up -d

# Wait for PostgreSQL ready
Start-Sleep -Seconds 10

# Run migrations
uv run alembic upgrade head

# Verify system
uv run newsroom health

# Run tests
uv run pytest -v
```

## Verification Commands

After fixing the blocker, run:

```powershell
# 1. Database connectivity
uv run newsroom health

# 2. Migrations apply cleanly
uv run alembic upgrade head

# 3. Tests pass
uv run pytest -v

# 4. Linters pass
uv run ruff check src/ tests/
uv run mypy src/newsroom

# 5. All scripts execute without errors
.\scripts\health.ps1
.\scripts\lint.ps1
.\scripts\test.ps1
```

## Files Created

```
newsroom/
├── .env                          # Config (gitignored)
├── .env.example                  # Template
├── .gitignore
├── pyproject.toml                # uv project definition
├── uv.lock                       # Locked dependencies
├── alembic.ini                   # Alembic config
├── compose.yaml                  # PostgreSQL service
├── src/newsroom/
│   ├── __init__.py
│   ├── config.py                 # Pydantic settings
│   ├── logging.py                # JSON formatter
│   ├── cli/
│   │   ├── __init__.py
│   │   └── main.py               # CLI entry point
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── models.py             # SQLAlchemy models
│   │   ├── database.py           # Session management
│   │   └── migrations/
│   │       ├── env.py            # Alembic environment
│   │       ├── script.py.mako
│   │       └── versions/         # (pending initial migration)
│   ├── sources/
│   │   └── __init__.py
│   ├── processing/
│   │   └── __init__.py
│   └── digest/
│       └── __init__.py
├── tests/
│   ├── conftest.py               # Pytest fixtures
│   └── test_models.py            # Model tests
├── scripts/
│   ├── setup.ps1
│   ├── db-up.ps1
│   ├── db-down.ps1
│   ├── migrate.ps1
│   ├── health.ps1
│   ├── lint.ps1
│   ├── test.ps1
│   ├── collect.ps1               # (M2 stub)
│   ├── process.ps1               # (M2 stub)
│   ├── digest.ps1                # (M2 stub)
│   └── validate-sources.ps1      # (M2 stub)
├── M1_STATUS.md                  # This file
├── STATUS.md                     # Updated project status
└── TASKS_SIMPLIFIED.md           # Simplified task list
```

## Commits

```bash
feat: M1 foundation - Python package, PostgreSQL, migrations, CLI, scripts
```

## Next Steps

1. **User action required**: Run the manual fix above to reset Docker volume
2. **Then proceed to M2**: First complete pipeline (RSS/GitHub → Persian preview)

## M1 Exit Criteria

- ✅ Scripts work on Windows PowerShell
- ⏸️ Database migrates (blocked by password)
- ⏸️ Health command runs (blocked by password)
- ⏸️ Basic tests pass (blocked by password)

**Status**: M1 implementation complete, environmental blocker requires manual intervention.
