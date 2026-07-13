$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== System Health Check ===" -ForegroundColor Cyan
Write-Host ""

$allOk = $true

# Check Docker
Write-Host "Checking Docker..." -ForegroundColor Yellow
if (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Host "  [OK] Docker installed" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] Docker not found" -ForegroundColor Red
    $allOk = $false
}

# Check PostgreSQL container
Write-Host "Checking PostgreSQL container..." -ForegroundColor Yellow
$containerStatus = docker ps --filter "name=newsroom-db" --format "{{.Status}}" 2>$null
if ($containerStatus -match "Up") {
    Write-Host "  [OK] PostgreSQL container running" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] PostgreSQL container not running" -ForegroundColor Red
    Write-Host "         Run: .\scripts\db-up.ps1" -ForegroundColor Gray
    $allOk = $false
}

# Check database connection
Write-Host "Checking database connection..." -ForegroundColor Yellow
try {
    docker exec newsroom-db pg_isready -U newsroom > $null 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] Database accepting connections" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] Database not ready" -ForegroundColor Red
        $allOk = $false
    }
} catch {
    Write-Host "  [FAIL] Cannot check database" -ForegroundColor Red
    $allOk = $false
}

# Check Python
Write-Host "Checking Python..." -ForegroundColor Yellow
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonVersion = python --version 2>&1
    Write-Host "  [OK] Python installed: $pythonVersion" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] Python not found" -ForegroundColor Red
    $allOk = $false
}

# Check uv
Write-Host "Checking uv..." -ForegroundColor Yellow
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "  [OK] uv installed" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] uv not found" -ForegroundColor Red
    Write-Host "         Run: pip install uv" -ForegroundColor Gray
    $allOk = $false
}

# Check .env
Write-Host "Checking .env..." -ForegroundColor Yellow
$envPath = Join-Path $RepoRoot ".env"
if (Test-Path $envPath) {
    Write-Host "  [OK] .env exists" -ForegroundColor Green
} else {
    Write-Host "  [WARN] .env not found" -ForegroundColor Yellow
    Write-Host "         Copy from .env.example" -ForegroundColor Gray
}

Write-Host ""
if ($allOk) {
    Write-Host "=== All Checks Passed ===" -ForegroundColor Green
    exit 0
} else {
    Write-Host "=== Some Checks Failed ===" -ForegroundColor Red
    exit 1
}
