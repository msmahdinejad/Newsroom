# Gate 6: production startup — one command starts the full stack.
# Starts PostgreSQL, migrations, scheduler, collector (native RSS/GitHub/
# Telegram-MTProto/Reddit/web_page/YouTube), Agent-Reach worker, editorial
# report-worker, Telegram ingestor, and Telegram output bot. Services use
# persistent named volumes, health checks, and restart policies. A complete
# restart retains the source registry, cursors, source health, scheduler
# state, X access state, MTProto session, reports, deliveries, and Telegram
# message IDs.

param([switch]$Wait = $true)

$ErrorActionPreference = "Stop"
Write-Host "[gate6] starting production stack (docker compose up -d)..." -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }

if ($Wait) {
    Write-Host "[gate6] waiting for service health..." -ForegroundColor Cyan
    docker compose up -d --wait 2>$null
}

Start-Sleep 5
Write-Host "[gate6] service status:" -ForegroundColor Cyan
docker compose ps --format "table {{.Name}}\t{{.Status}}"

Write-Host "[gate6] production stack started." -ForegroundColor Green
Write-Host "  - Import + activate the source inventory (one command, no DB/YAML editing):"
Write-Host "      uv run newsroom sources reconcile"
Write-Host "  - Trigger a scheduled-style report now:"
Write-Host "      uv run newsroom pipeline run"
Write-Host "  - Inspect health: uv run newsroom health   |   docker compose ps"
