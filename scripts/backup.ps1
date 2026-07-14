$ErrorActionPreference = "Stop"
# Backup PostgreSQL database
$repoDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$backupDir = Join-Path $repoDir "backups"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupFile = Join-Path $backupDir "newsroom-$timestamp.sql"

Write-Host "[BACKUP] Creating database backup..."
docker exec newsroom-postgres pg_dump -U newsroom newsroom > $backupFile

if ($LASTEXITCODE -ne 0) {
    Write-Error "[ERROR] Backup failed"
    exit 1
}

$size = (Get-Item $backupFile).Length
Write-Host "[OK] Backup saved: $backupFile ($size bytes)"
