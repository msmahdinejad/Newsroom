$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Running linters..." -ForegroundColor Cyan
Write-Host ""

$allOk = $true

# Ruff
Write-Host "Running ruff..." -ForegroundColor Yellow
Push-Location $RepoRoot
try {
    uv run ruff check newsroom/
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] Ruff found issues" -ForegroundColor Red
        $allOk = $false
    } else {
        Write-Host "[OK] Ruff passed" -ForegroundColor Green
    }
} finally {
    Pop-Location
}
Write-Host ""

# Ruff format check
Write-Host "Checking code formatting..." -ForegroundColor Yellow
Push-Location $RepoRoot
try {
    uv run ruff format --check newsroom/
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] Code formatting issues found" -ForegroundColor Red
        Write-Host "       Run: uv run ruff format newsroom/" -ForegroundColor Gray
        $allOk = $false
    } else {
        Write-Host "[OK] Formatting correct" -ForegroundColor Green
    }
} finally {
    Pop-Location
}
Write-Host ""

# mypy (optional, may not be fully configured yet)
Write-Host "Running mypy..." -ForegroundColor Yellow
Push-Location $RepoRoot
try {
    uv run mypy newsroom/ 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] mypy found issues (optional)" -ForegroundColor Yellow
    } else {
        Write-Host "[OK] mypy passed" -ForegroundColor Green
    }
} finally {
    Pop-Location
}

Write-Host ""
if ($allOk) {
    Write-Host "[OK] All linters passed" -ForegroundColor Green
    exit 0
} else {
    Write-Error "Linter failures detected"
    exit 1
}
