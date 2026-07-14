$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$BackupDir = Join-Path $RepoRoot "backups"
if (-not (Test-Path $BackupDir)) { New-Item -ItemType Directory -Path $BackupDir | Out-Null }

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dumpFile = Join-Path $BackupDir "newsroom-$timestamp.sql"

Write-Host "=== Newsroom: Database backup ==="
docker compose exec -T postgres pg_dump -U newsroom -d newsroom > $dumpFile
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $dumpFile)) {
    Write-Host "[ERROR] pg_dump failed"
    exit 1
}

$size = (Get-Item $dumpFile).Length
Write-Host "[OK] Backup saved: $dumpFile ($size bytes)"
exit 0
