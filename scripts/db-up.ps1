$ErrorActionPreference = "Stop"

Write-Host "Starting PostgreSQL..." -ForegroundColor Cyan
docker compose up -d

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] PostgreSQL started" -ForegroundColor Green
    
    Write-Host "Waiting for database to be ready..." -ForegroundColor Cyan
    $maxAttempts = 30
    $attempt = 0
    $ready = $false
    
    while ($attempt -lt $maxAttempts) {
        docker compose exec -T postgres pg_isready -U newsroom 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Database ready" -ForegroundColor Green
            $ready = $true
            break
        }
        $attempt++
        Start-Sleep -Seconds 1
    }
    
    if ($ready) {
        exit 0
    } else {
        Write-Host "[ERROR] Database failed to become ready" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[ERROR] Failed to start PostgreSQL" -ForegroundColor Red
    exit 1
}
