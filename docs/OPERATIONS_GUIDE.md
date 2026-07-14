# Operations Guide

## Start
```powershell
docker compose up -d postgres
docker compose run --rm migrate
docker compose up -d
```

## Stop
```powershell
docker compose down
```

## Backup
```powershell
.\scripts\backup.ps1
# → backups/newsroom-YYYYMMDD-HHmmss.sql
```

## Restore
```powershell
.\scripts\restore.ps1 -File newsroom-20260714-142414.sql
```

## Seed sources
```powershell
python scripts\seed_sources.py
```

## Run pipeline manually
```powershell
python scripts\run_pipeline.py
```

## Health check
```powershell
docker compose ps
docker exec newsroom-postgres pg_isready -U newsroom
```

## Logs
```powershell
docker compose logs -f collector
docker compose logs -f scheduler
docker compose logs -f telegram-bot
```

## Migrations
```powershell
docker compose run --rm migrate
```

## Test
```powershell
python -m pytest tests/ -q
python -m ruff check src/
```
