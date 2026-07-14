$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== Newsroom: Container status ==="
docker compose ps
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] docker compose ps failed"; exit 1 }

Write-Host ""
Write-Host "=== Health check ==="
uv run newsroom health
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Health check failed"; exit 1 }

Write-Host "[OK] All healthy"
exit 0
