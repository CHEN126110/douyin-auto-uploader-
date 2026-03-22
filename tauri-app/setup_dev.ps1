# 抖音袜子发布工具 v4.0 - 开发环境配置脚本 (PowerShell)

$ErrorActionPreference = "Stop"

Write-Host "========================================"
Write-Host "  抖音袜子发布工具 v4.0 开发环境配置"
Write-Host "========================================"
Write-Host ""

# 检查 Node.js
Write-Host "[1/5] 检查 Node.js..." -ForegroundColor Cyan
try {
    $nodeVersion = node --version
    Write-Host "✅ Node.js $nodeVersion 已安装" -ForegroundColor Green
} catch {
    Write-Host "❌ 未找到 Node.js，请先安装 Node.js 18+" -ForegroundColor Red
    Write-Host "下载地址: https://nodejs.org/"
    exit 1
}

# 检查 Rust
Write-Host "[2/5] 检查 Rust..." -ForegroundColor Cyan
try {
    $rustVersion = rustc --version
    Write-Host "✅ $rustVersion 已安装" -ForegroundColor Green
} catch {
    Write-Host "❌ 未找到 Rust，请先安装 Rust" -ForegroundColor Red
    Write-Host "安装命令: winget install Rustlang.Rustup"
    exit 1
}

# 检查 Python
Write-Host "[3/5] 检查 Python..." -ForegroundColor Cyan
try {
    $pythonVersion = python --version
    Write-Host "✅ $pythonVersion 已安装" -ForegroundColor Green
} catch {
    Write-Host "❌ 未找到 Python，请先安装 Python 3.11+" -ForegroundColor Red
    exit 1
}

# 安装前端依赖
Write-Host "[4/5] 安装前端依赖..." -ForegroundColor Cyan
Push-Location $PSScriptRoot
try {
    npm install
    Write-Host "✅ 前端依赖安装完成" -ForegroundColor Green
} catch {
    Write-Host "❌ 前端依赖安装失败: $_" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location

# 安装 Python 依赖
Write-Host "[5/5] 安装 Python 依赖..." -ForegroundColor Cyan
Push-Location (Join-Path $PSScriptRoot "..")
try {
    pip install -r requirements.txt
    Write-Host "✅ Python 依赖安装完成" -ForegroundColor Green
} catch {
    Write-Host "⚠️ Python 依赖安装可能不完整" -ForegroundColor Yellow
}
Pop-Location

Write-Host ""
Write-Host "========================================"
Write-Host "  ✅ 开发环境配置完成！" -ForegroundColor Green
Write-Host "========================================"
Write-Host ""
Write-Host "开发命令:" -ForegroundColor Cyan
Write-Host "  npm run dev          - 启动前端开发服务器"
Write-Host "  npm run tauri:dev    - 启动 Tauri 开发模式"
Write-Host "  npm run tauri:build  - 构建生产版本"
Write-Host ""
Write-Host "后端命令:" -ForegroundColor Cyan
Write-Host "  python python-sidecar/app.py  - 启动 Python 后端"
Write-Host ""
Read-Host "按 Enter 键退出"
