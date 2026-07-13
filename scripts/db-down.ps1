$ErrorActionPreference = "Stop"

Write-Host "Stopping PostgreSQL..." -ForegroundColor Cyan
docker compose down

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ PostgreSQL stopped" -ForegroundColor Green
    exit 0
} else {
    Write-Host "✗ Failed to stop PostgreSQL" -ForegroundColor Red
    exit 1
}
