# One-command production startup for the complete persistent stack.

param([switch]$Wait = $true)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "Starting production stack..." -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }

if ($Wait) {
    docker compose up -d --wait 2>$null
    if ($LASTEXITCODE -ne 0) { throw "production services did not become healthy" }
}

Write-Host "Production service status:" -ForegroundColor Cyan
docker compose ps --format "table {{.Name}}\t{{.Status}}"

Write-Host "Production stack started." -ForegroundColor Green
Write-Host "  Source inventory: uv run newsroom sources reconcile"
Write-Host "  Scheduled-style report: uv run newsroom pipeline run"
Write-Host "  Health: powershell -File scripts/health.ps1"
