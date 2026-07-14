$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== Newsroom: Starting stack ==="
docker compose up -d
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] docker compose up failed"; exit 1 }

Write-Host "Waiting for containers to be healthy..."
$maxAttempts = 60
$attempt = 0
while ($attempt -lt $maxAttempts) {
    $healthy = $true
    $ps = docker compose ps --format json 2>$null | ForEach-Object {
        $_ | ConvertFrom-Json
    }
    foreach ($svc in $ps) {
        if ($svc.Health -and $svc.Health -ne "healthy") { $healthy = $false }
    }
    if ($healthy -and $ps.Count -gt 0) { break }
    $attempt++
    Start-Sleep -Seconds 2
}

if (-not $healthy) {
    Write-Host "[ERROR] Containers did not become healthy in $maxAttempts attempts"
    exit 1
}

Write-Host "[OK] Stack is up and healthy"
exit 0
