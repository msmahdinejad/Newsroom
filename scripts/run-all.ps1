$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== Running Complete Pipeline ===" -ForegroundColor Cyan
Write-Host ""

$startTime = Get-Date

# Collect
Write-Host "[1/3] Collecting..." -ForegroundColor Yellow
& (Join-Path $PSScriptRoot "collect.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Error "Collection failed"
    exit 1
}
Write-Host ""

# Process
Write-Host "[2/3] Processing..." -ForegroundColor Yellow
& (Join-Path $PSScriptRoot "process.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Error "Processing failed"
    exit 1
}
Write-Host ""

# Digest
Write-Host "[3/3] Generating digests..." -ForegroundColor Yellow
& (Join-Path $PSScriptRoot "digest.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Error "Digest generation failed"
    exit 1
}
Write-Host ""

$endTime = Get-Date
$duration = $endTime - $startTime

Write-Host "=== Pipeline Complete ===" -ForegroundColor Green
Write-Host "Duration: $($duration.TotalSeconds) seconds" -ForegroundColor Cyan
