$ErrorActionPreference = "Stop"

Write-Host "Checking system health..." -ForegroundColor Cyan
uv run newsroom health

if ($LASTEXITCODE -eq 0) {
    exit 0
} else {
    Write-Host "[ERROR] Health check failed" -ForegroundColor Red
    exit 1
}
