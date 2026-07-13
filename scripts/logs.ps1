$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$logFile = Join-Path $RepoRoot "logs\newsroom.log"

if (-not (Test-Path $logFile)) {
    Write-Host "Log file not found: $logFile" -ForegroundColor Yellow
    Write-Host "Logs will be created when pipeline runs." -ForegroundColor Gray
    exit 0
}

Write-Host "Showing logs from: $logFile" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host ""

Get-Content $logFile -Tail 50 -Wait
