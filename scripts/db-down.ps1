$ErrorActionPreference = "Stop"

Write-Host "Stopping PostgreSQL..." -ForegroundColor Cyan
docker compose down

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] PostgreSQL stopped" -ForegroundColor Green
    exit 0
} else {
    Write-Host "[ERROR] Failed to stop PostgreSQL" -ForegroundColor Red
    exit 1
}
