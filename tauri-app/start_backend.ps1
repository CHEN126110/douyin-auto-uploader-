# PowerShell 兼容入口（已收口到根目录 start_frontend.bat）

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "入口已收口到 start_frontend.bat" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot
Write-Host "已停用 tauri-app 下独立后端入口，避免多入口冲突。" -ForegroundColor Yellow
Write-Host "正在跳转到统一入口..." -ForegroundColor Yellow
Write-Host ""
& "$projectRoot\start_frontend.bat"
