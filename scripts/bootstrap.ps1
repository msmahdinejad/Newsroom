$ErrorActionPreference = "Stop"

Write-Host "=== Newsroom Bootstrap ==="

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "Checking Docker..."
docker --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Docker not found"
    exit 1
}
Write-Host "[OK] Docker"

if (-not (Test-Path ".env")) {
    Write-Host "Creating .env..."
    @"
DATABASE_URL=postgresql+psycopg://newsroom:newsroom_dev@127.0.0.1:55432/newsroom
POSTGRES_PASSWORD=newsroom_dev
NEWSROOM_POSTGRES_HOST_PORT=55432
LOG_LEVEL=INFO
LOG_FORMAT=json
COLLECTION_TIMEOUT_CONNECT=30
COLLECTION_TIMEOUT_READ=60
COLLECTION_MAX_SIZE_MB=1
DEDUP_TIME_WINDOW_HOURS=24
CLUSTER_KEYWORD_THRESHOLD=0.5
"@ | Set-Content .env
}

Write-Host "Installing dependencies..."
uv sync

Write-Host "Starting PostgreSQL..."
docker compose up -d postgres

Write-Host "Waiting for health..."
Start-Sleep 10

Write-Host "Running migrations..."
uv run alembic upgrade head

Write-Host "[OK] Bootstrap complete"
