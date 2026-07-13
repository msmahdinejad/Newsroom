$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Validating sources (dry-run, no data stored)..." -ForegroundColor Cyan

Push-Location $RepoRoot
try {
    uv run python -m newsroom.cli validate-sources
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Source validation failed"
        exit 1
    }
    Write-Host "[OK] Source validation complete" -ForegroundColor Green
} finally {
    Pop-Location
}
