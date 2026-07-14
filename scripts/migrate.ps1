$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== Newsroom: Running migrations ==="
uv run alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Migration failed"; exit 1 }

Write-Host "[OK] Migrations applied"
exit 0
