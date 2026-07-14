$ErrorActionPreference = "Stop"

param(
    [Parameter(Mandatory=$true)]
    [string]$File
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# Resolve relative paths
if (-not [System.IO.Path]::IsPathRooted($File)) {
    $File = Join-Path (Get-Location) $File
}

if (-not (Test-Path $File)) {
    Write-Host "[ERROR] Backup file not found: $File"
    exit 1
}

Write-Host "=== Newsroom: Database restore ==="
Write-Host "Restoring from: $File"
Write-Host "This will REPLACE all data in the newsroom database."
$response = Read-Host "Type 'yes' to continue"
if ($response -ne "yes") {
    Write-Host "Restore cancelled."
    exit 1
}

Get-Content -Path $File -Raw | docker compose exec -T postgres psql -U newsroom -d newsroom
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Restore failed"; exit 1 }

Write-Host "[OK] Restore complete"
exit 0
