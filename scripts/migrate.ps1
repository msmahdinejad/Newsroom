$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Running database migrations..." -ForegroundColor Cyan

Push-Location $RepoRoot
try {
    uv run alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Migration failed"
        exit 1
    }
    Write-Host "[OK] Migrations applied" -ForegroundColor Green
} finally {
    Pop-Location
}
