$ErrorActionPreference = "Stop"
# Restore PostgreSQL database from backup file
param(
    [Parameter(Mandatory=$true)]
    [string]$File
)

$repoDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$backupFile = Join-Path $repoDir "backups" $File

if (-not (Test-Path $backupFile)) {
    Write-Error "[ERROR] Backup file not found: $backupFile"
    exit 1
}

Write-Host "[RESTORE] Restoring from: $File"
Write-Host "[RESTORE] Dropping and recreating database..."

# Drop and recreate to ensure clean restore
docker exec newsroom-postgres psql -U newsroom -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "[ERROR] Schema reset failed"
    exit 1
}

Write-Host "[RESTORE] Loading backup data..."
Get-Content $backupFile | docker exec -i newsroom-postgres psql -U newsroom newsroom
if ($LASTEXITCODE -ne 0) {
    Write-Error "[ERROR] Restore failed"
    exit 1
}

Write-Host "[OK] Database restored from $File"
