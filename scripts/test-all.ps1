$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== Newsroom: Running all tests ==="
Write-Host "[1/2] Ruff..."
uv run ruff check src/ tests/
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Ruff failed"; exit 1 }
Write-Host "[OK] Ruff passed"

Write-Host "[2/2] Pytest..."
uv run pytest tests/ -v --tb=short
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Pytest failed"; exit 1 }
Write-Host "[OK] Pytest passed"

Write-Host "[OK] All tests passed"
exit 0
