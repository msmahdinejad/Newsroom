$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Resetting test data..." -ForegroundColor Cyan
Write-Host ""

Write-Host "WARNING: This will delete all data in the database!" -ForegroundColor Yellow
$confirm = Read-Host "Type 'yes' to continue"

if ($confirm -ne "yes") {
    Write-Host "Cancelled" -ForegroundColor Gray
    exit 0
}

Write-Host ""
Write-Host "Truncating all tables..." -ForegroundColor Yellow

Push-Location $RepoRoot
try {
    uv run python -m newsroom.cli reset-data
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Reset failed"
        exit 1
    }
    Write-Host "[OK] Database reset complete" -ForegroundColor Green
} finally {
    Pop-Location
}
