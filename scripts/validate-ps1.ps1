$ErrorActionPreference = "Stop"

Write-Host "Validating PowerShell scripts..." -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $PSCommandPath
$scripts = Get-ChildItem -Path $scriptDir -Filter "*.ps1"
$failed = @()

foreach ($script in $scripts) {
    $tokens = $null
    $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$tokens, [ref]$errors)
    
    if ($errors.Count -gt 0) {
        Write-Host "[ERROR] $($script.Name) - Parse failed" -ForegroundColor Red
        foreach ($err in $errors) {
            Write-Host "  Line $($err.Extent.StartLineNumber): $($err.Message)" -ForegroundColor Red
        }
        $failed += $script.Name
    } else {
        Write-Host "[OK] $($script.Name)" -ForegroundColor Green
    }
}

if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "[ERROR] $($failed.Count) script(s) failed validation" -ForegroundColor Red
    exit 1
} else {
    Write-Host ""
    Write-Host "[OK] All $($scripts.Count) scripts validated successfully" -ForegroundColor Green
    exit 0
}
