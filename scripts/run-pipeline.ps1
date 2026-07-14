$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== Newsroom: Running pipeline ==="
uv run python scripts/run_pipeline.py
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Pipeline failed"; exit 1 }

Write-Host "[OK] Pipeline complete"
exit 0
