$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$exitCode = 0

Write-Host "========================================"
Write-Host "  Douyin Sock Publisher v4.0 - Tauri Dev"
Write-Host "========================================"
Write-Host ""

try {
    Set-Location $projectRoot
    Write-Host "Current directory: $projectRoot"
    Write-Host ""
    Write-Host "[START] Running npm run tauri:dev ..." -ForegroundColor Cyan
    Write-Host ""

    npm run tauri:dev
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Write-Host ""
        Write-Host "[DONE] Process exited." -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "[EXIT] Process exit code: $exitCode" -ForegroundColor Yellow
    }
} catch {
    $exitCode = 1
    Write-Host ""
    Write-Host "[ERROR] Startup failed: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    Write-Host ""
    Read-Host "Press Enter to keep the window open, then exit" | Out-Null
    exit $exitCode
}
