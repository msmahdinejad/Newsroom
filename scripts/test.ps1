$ErrorActionPreference = "Stop"
Write-Host "Running tests..." -ForegroundColor Cyan
uv run pytest tests/ -v --tb=short
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Tests passed" -ForegroundColor Green
    exit 0
} else {
    Write-Host "✗ Tests failed" -ForegroundColor Red
    exit 1
}
