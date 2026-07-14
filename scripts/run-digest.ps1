$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== Newsroom: Generating and delivering digest ==="
uv run newsroom digest generate
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Digest generation failed"; exit 1 }
Write-Host "[OK] Digest generated"

uv run newsroom digest deliver
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Digest delivery failed"; exit 1 }
Write-Host "[OK] Digest delivered"

exit 0
