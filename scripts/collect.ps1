$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "Collecting from native CLI sources..." -ForegroundColor Cyan
uv run newsroom collect @args
exit $LASTEXITCODE
