$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== Newsroom: Stopping stack ==="
docker compose down
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] docker compose down failed"; exit 1 }

Write-Host "[OK] Stack stopped"
exit 0
