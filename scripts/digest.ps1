$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "Generating Persian report..." -ForegroundColor Cyan
uv run newsroom report generate
exit $LASTEXITCODE
