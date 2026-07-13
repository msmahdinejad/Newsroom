$ErrorActionPreference = "Stop"

Write-Host "Running database migrations..." -ForegroundColor Cyan
uv run alembic upgrade head

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Migrations applied" -ForegroundColor Green
    exit 0
} else {
    Write-Host "✗ Migration failed" -ForegroundColor Red
    exit 1
}
