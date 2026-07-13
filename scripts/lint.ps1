$ErrorActionPreference = "Stop"
Write-Host "Running linters..." -ForegroundColor Cyan
uv run ruff check src/ tests/
if ($LASTEXITCODE -ne 0) { Write-Host "✗ Ruff failed" -ForegroundColor Red; exit 1 }
uv run mypy src/newsroom
if ($LASTEXITCODE -eq 0) { Write-Host "✓ Linters passed" -ForegroundColor Green; exit 0 }
else { Write-Host "✗ Mypy failed" -ForegroundColor Red; exit 1 }
