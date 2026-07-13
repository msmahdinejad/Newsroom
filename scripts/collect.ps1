$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Collecting from all enabled sources..." -ForegroundColor Cyan

Push-Location $RepoRoot
try {
    uv run python -m newsroom.cli collect
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Collection failed"
        exit 1
    }
    Write-Host "[OK] Collection complete" -ForegroundColor Green
} finally {
    Pop-Location
}
