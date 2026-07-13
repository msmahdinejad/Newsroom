$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Starting PostgreSQL..." -ForegroundColor Cyan

Push-Location $RepoRoot
try {
    docker compose up -d
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to start PostgreSQL"
        exit 1
    }
    Write-Host "[OK] PostgreSQL started" -ForegroundColor Green
} finally {
    Pop-Location
}
