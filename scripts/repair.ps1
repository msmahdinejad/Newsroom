$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== Newsroom: Repair ==="
Write-Host "[1/3] Restarting containers..."
docker compose down
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] docker compose down failed"; exit 1 }
docker compose up -d
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] docker compose up failed"; exit 1 }

Write-Host "[2/3] Waiting for healthy..."
$attempt = 0
$ready = $false
while ($attempt -lt 60) {
    $state = docker compose ps -q postgres 2>$null
    if ($state) {
        $status = docker inspect -f '{{.State.Health.Status}}' $state 2>$null
        if ($status -eq "healthy") { $ready = $true; break }
    }
    $attempt++
    Start-Sleep -Seconds 2
}
if (-not $ready) { Write-Host "[ERROR] PostgreSQL did not become healthy"; exit 1 }

Write-Host "[3/3] Running migrations..."
uv run alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Migration failed"; exit 1 }

Write-Host "[OK] Repair complete"
exit 0
