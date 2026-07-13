$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Generating Persian digest candidates..." -ForegroundColor Cyan

Push-Location $RepoRoot
try {
    uv run python -m newsroom.cli digest
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Digest generation failed"
        exit 1
    }
    Write-Host "[OK] Digest generation complete" -ForegroundColor Green
} finally {
    Pop-Location
}
