$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "Processing collected items..." -ForegroundColor Cyan
uv run newsroom process all
exit $LASTEXITCODE
