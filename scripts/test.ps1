$ErrorActionPreference = "Stop"
Write-Host "Running tests..." -ForegroundColor Cyan
uv run pytest tests/ -v --tb=short
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Tests passed" -ForegroundColor Green
    exit 0
} else {
    Write-Host "[ERROR] Tests failed" -ForegroundColor Red
    exit 1
}
