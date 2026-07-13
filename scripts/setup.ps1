$ErrorActionPreference = "Stop"

Write-Host "Setting up newsroom environment..." -ForegroundColor Cyan

# Create .env if missing
if (-not (Test-Path ".env")) {
    Write-Host "Creating .env from template..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
}

# Install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Cyan
uv sync --extra dev

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Failed to install dependencies" -ForegroundColor Red
    exit 1
}

# Start database
Write-Host "Starting database..." -ForegroundColor Cyan
& "$PSScriptRoot\db-up.ps1"

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Failed to start database" -ForegroundColor Red
    exit 1
}

# Run migrations
Write-Host "Running migrations..." -ForegroundColor Cyan
& "$PSScriptRoot\migrate.ps1"

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Failed to run migrations" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "✓ Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  .\scripts\health.ps1          - Check system health"
Write-Host "  .\scripts\collect.ps1         - Collect from sources"
Write-Host "  .\scripts\process.ps1         - Process collected items"
