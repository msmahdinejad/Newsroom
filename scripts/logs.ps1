$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== Newsroom: Container logs (last 50 lines) ==="
docker compose logs --tail 50
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Failed to fetch logs"; exit 1 }

exit 0
