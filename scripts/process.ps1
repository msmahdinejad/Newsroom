$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Processing pipeline: normalize → dedupe → cluster..." -ForegroundColor Cyan

Push-Location $RepoRoot
try {
    uv run python -m newsroom.cli process
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Processing failed"
        exit 1
    }
    Write-Host "[OK] Processing complete" -ForegroundColor Green
} finally {
    Pop-Location
}
