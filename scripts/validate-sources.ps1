$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "Checking source inventory reconciliation..." -ForegroundColor Cyan
uv run newsroom sources status
exit $LASTEXITCODE
