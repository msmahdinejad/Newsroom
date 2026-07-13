$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Running tests..." -ForegroundColor Cyan

Push-Location $RepoRoot
try {
    uv run pytest -v
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Tests failed"
        exit 1
    }
    Write-Host "[OK] Tests passed" -ForegroundColor Green
} finally {
    Pop-Location
}
