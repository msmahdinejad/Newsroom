$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== Newsroom: Environment doctor ==="
$fail = 0

# Docker
Write-Host -NoNewline "  Docker...... "
$null = docker --version 2>&1
if ($LASTEXITCODE -eq 0) { Write-Host "[OK]" } else { Write-Host "[MISSING]"; $fail = 1 }

# Docker daemon running
Write-Host -NoNewline "  Docker daemon "
$null = docker info 2>&1
if ($LASTEXITCODE -eq 0) { Write-Host "[OK]" } else { Write-Host "[NOT RUNNING]"; $fail = 1 }

# Python
Write-Host -NoNewline "  Python...... "
$null = python --version 2>&1
if ($LASTEXITCODE -eq 0) { Write-Host "[OK]" } else { Write-Host "[MISSING]"; $fail = 1 }

# uv
Write-Host -NoNewline "  uv.......... "
$null = uv --version 2>&1
if ($LASTEXITCODE -eq 0) { Write-Host "[OK]" } else { Write-Host "[MISSING]"; $fail = 1 }

# PostgreSQL container
Write-Host -NoNewline "  PostgreSQL.. "
$state = docker compose ps -q postgres 2>$null
if ($state) {
    $status = docker inspect -f '{{.State.Health.Status}}' $state 2>$null
    if ($status -eq "healthy") { Write-Host "[OK]" }
    else { Write-Host "[UNHEALTHY: $status]"; $fail = 1 }
} else {
    Write-Host "[NOT RUNNING]"
    $fail = 1
}

# .env file
Write-Host -NoNewline "  .env file... "
if (Test-Path (Join-Path $RepoRoot ".env")) { Write-Host "[OK]" } else { Write-Host "[MISSING]"; $fail = 1 }

Write-Host ""
if ($fail -ne 0) { Write-Host "[ERROR] Doctor check failed"; exit 1 }
Write-Host "[OK] All checks passed"
exit 0
