$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "Checking database and production services..." -ForegroundColor Cyan
uv run newsroom health
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Database health check failed" -ForegroundColor Red
    exit 1
}

docker compose config -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Docker Compose configuration is invalid" -ForegroundColor Red
    exit 1
}

$requiredServices = @(
    "postgres",
    "collector",
    "report-worker",
    "scheduler",
    "telegram-bot",
    "telegram-ingestor",
    "agent-reach-worker"
)
$serviceRows = @(
    docker compose ps --format json |
        ForEach-Object { $_ | ConvertFrom-Json }
)
$failures = @()
foreach ($service in $requiredServices) {
    $row = $serviceRows | Where-Object { $_.Service -eq $service } | Select-Object -First 1
    if ($null -eq $row) {
        $failures += "${service}: missing"
        continue
    }
    if ($row.State -ne "running") {
        $failures += "${service}: $($row.State)"
        continue
    }
    if ($row.Health -and $row.Health -ne "healthy") {
        $failures += "${service}: $($row.Health)"
    }
}

if ($failures.Count -gt 0) {
    foreach ($failure in $failures) {
        Write-Host "[ERROR] $failure" -ForegroundColor Red
    }
    exit 1
}

Write-Host "[OK] Database and all required production services are healthy" -ForegroundColor Green
exit 0
