$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Stopping PostgreSQL..." -ForegroundColor Cyan

Push-Location $RepoRoot
try {
    docker compose down
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to stop PostgreSQL"
        exit 1
    }
    Write-Host "[OK] PostgreSQL stopped" -ForegroundColor Green
} finally {
    Pop-Location
}
