# M1 Complete Verification Sequence

Execute this exact sequence after incident repairs complete.

## Prerequisites

- [ ] PowerShell encoding fixed (subagent workstream A)
- [ ] Database password reconciled (subagent workstream B)
- [ ] Git working tree clean or incident fixes committed

## Verification Gates (In Order)

### Gate 1: Environment Setup
```powershell
cd [REDACTED]\OneDrive\Desktop\newsroom

# Verify dependencies
uv sync --extra dev
# Expected: Success, dependencies installed

# Verify Docker
docker compose ps
# Expected: newsroom-postgres running (healthy)
```

### Gate 2: PowerShell Parse Validation
```powershell
# Run the new validator created by subagent
.\scripts\validate-ps1.ps1
# Expected: All 14 scripts parse successfully
```

### Gate 3: Database Connectivity
```powershell
# Test raw PostgreSQL connection
docker compose exec postgres psql -U newsroom -d newsroom -c "SELECT 1;"
# Expected: Returns 1

# Test Python connection
uv run python -c "from newsroom.storage.database import engine; from sqlalchemy import text; conn = engine.connect(); print(conn.execute(text('SELECT 1')).scalar()); conn.close()"
# Expected: Returns 1
```

### Gate 4: Initial Migration
```powershell
# Generate initial migration from models
uv run alembic revision --autogenerate -m "Initial schema"
# Expected: Creates migration file in src/newsroom/storage/migrations/versions/

# Apply migration
uv run alembic upgrade head
# Expected: Success, tables created

# Verify current revision
uv run alembic current
# Expected: Shows current revision hash
```

### Gate 5: Health Check
```powershell
uv run newsroom health
# Expected: "All health checks passed", exit 0

.\scripts\health.ps1
# Expected: [OK] Health check passed, exit 0
```

### Gate 6: Code Quality
```powershell
# Linting
uv run ruff check src/ tests/
# Expected: All checks passed!

# Type checking
uv run mypy src/newsroom
# Expected: Success: no issues found

# Combined script
.\scripts\lint.ps1
# Expected: [OK] Linters passed, exit 0
```

### Gate 7: Test Suite
```powershell
# Run all tests
uv run pytest tests/ -v
# Expected: All tests pass

# Script wrapper
.\scripts\test.ps1
# Expected: [OK] Tests passed, exit 0
```

### Gate 8: Script Validation
```powershell
# Verify each script executes without parse errors
.\scripts\db-up.ps1      # Already running, should be idempotent
.\scripts\health.ps1     # Should pass
.\scripts\lint.ps1       # Should pass
.\scripts\test.ps1       # Should pass
.\scripts\migrate.ps1    # Already at head, should be no-op

# Stub scripts should execute without error (even if no-op)
.\scripts\collect.ps1
.\scripts\process.ps1
.\scripts\digest.ps1
.\scripts\validate-sources.ps1
```

### Gate 9: Database Schema Validation
```powershell
# Verify all tables exist
docker compose exec postgres psql -U newsroom -d newsroom -c "\dt"
# Expected: sources, raw_items, normalized_items, stories, digests, alembic_version

# Verify a table structure
docker compose exec postgres psql -U newsroom -d newsroom -c "\d sources"
# Expected: Shows columns matching models.py
```

### Gate 10: Restart Resilience
```powershell
# Stop everything
.\scripts\db-down.ps1

# Start fresh
.\scripts\db-up.ps1
Start-Sleep -Seconds 10

# Verify health after restart
uv run newsroom health
# Expected: Success (migrations persisted)
```

## Success Criteria

All 10 gates pass without manual intervention.

## On Failure

If any gate fails:
1. Capture exact error output
2. Note which gate failed
3. Do NOT proceed to next gate
4. Diagnose and fix
5. Restart verification from Gate 1

## After Success

1. Commit all incident fixes and M1 completion evidence
2. Update STATUS.md: M1 → Complete, M2 → In Progress
3. Immediately begin M2 implementation without stopping
