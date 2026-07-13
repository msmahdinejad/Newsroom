$ErrorActionPreference = "Stop"

# Setup script: Install dependencies, start database, run migrations
# Run this once after cloning the repository

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== Newsroom Setup ===" -ForegroundColor Cyan
Write-Host ""

# Check prerequisites
Write-Host "Checking prerequisites..." -ForegroundColor Yellow

# Check Docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker not found. Please install Docker Desktop."
    exit 1
}

# Check Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found. Please install Python 3.12."
    exit 1
}

$pythonVersion = python --version 2>&1
if ($pythonVersion -notmatch "Python 3\.12") {
    Write-Warning "Python 3.12 recommended. Found: $pythonVersion"
}

# Check uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..." -ForegroundColor Yellow
    pip install uv
}

Write-Host "[OK] Prerequisites checked" -ForegroundColor Green
Write-Host ""

# Install Python dependencies
Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
Push-Location $RepoRoot
try {
    uv pip install -e .
    Write-Host "[OK] Dependencies installed" -ForegroundColor Green
} catch {
    Write-Error "Failed to install dependencies: $_"
    exit 1
} finally {
    Pop-Location
}
Write-Host ""

# Create .env if needed
$envPath = Join-Path $RepoRoot ".env"
$envExamplePath = Join-Path $RepoRoot ".env.example"
if (-not (Test-Path $envPath)) {
    Write-Host "Creating .env from .env.example..." -ForegroundColor Yellow
    Copy-Item $envExamplePath $envPath
    Write-Host "[OK] .env created (review and edit as needed)" -ForegroundColor Green
} else {
    Write-Host "[SKIP] .env already exists" -ForegroundColor Gray
}
Write-Host ""

# Start database
Write-Host "Starting PostgreSQL..." -ForegroundColor Yellow
& (Join-Path $PSScriptRoot "db-up.ps1")
Write-Host ""

# Wait for database to be ready
Write-Host "Waiting for database..." -ForegroundColor Yellow
$maxAttempts = 30
$attempt = 0
while ($attempt -lt $maxAttempts) {
    $attempt++
    try {
        docker exec newsroom-db pg_isready -U newsroom > $null 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Database ready" -ForegroundColor Green
            break
        }
    } catch {}
    Start-Sleep -Seconds 1
}
if ($attempt -ge $maxAttempts) {
    Write-Error "Database failed to start"
    exit 1
}
Write-Host ""

# Run migrations
Write-Host "Running database migrations..." -ForegroundColor Yellow
& (Join-Path $PSScriptRoot "migrate.ps1")
Write-Host ""

# Done
Write-Host "=== Setup Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Review and edit .env if needed"
Write-Host "  2. Run: .\scripts\health.ps1 to verify system"
Write-Host "  3. Run: .\scripts\validate-sources.ps1 to test sources"
Write-Host "  4. Run: .\scripts\collect.ps1 to collect data"
Write-Host ""
