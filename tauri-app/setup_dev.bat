@echo off
chcp 65001 >nul
title 抖音袜子发布工具 v4.0 - 开发环境配置

echo ========================================
echo   抖音袜子发布工具 v4.0 开发环境配置
echo ========================================
echo.

:: 检查 Node.js
echo [1/5] 检查 Node.js...
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 未找到 Node.js，请先安装 Node.js 18+
    echo 下载地址: https://nodejs.org/
    pause
    exit /b 1
)
echo ✅ Node.js 已安装

:: 检查 Rust
echo [2/5] 检查 Rust...
rustc --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 未找到 Rust，请先安装 Rust
    echo 安装命令: winget install Rustlang.Rustup
    echo 或访问: https://www.rust-lang.org/tools/install
    pause
    exit /b 1
)
echo ✅ Rust 已安装

:: 检查 Python
echo [3/5] 检查 Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 未找到 Python，请先安装 Python 3.11+
    pause
    exit /b 1
)
echo ✅ Python 已安装

:: 安装前端依赖
echo [4/5] 安装前端依赖...
cd /d "%~dp0"
call npm install
if %errorlevel% neq 0 (
    echo ❌ 前端依赖安装失败
    pause
    exit /b 1
)
echo ✅ 前端依赖安装完成

:: 安装 Python 依赖
echo [5/5] 安装 Python 依赖...
cd /d "%~dp0.."
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ⚠️ Python 依赖安装可能不完整，请检查
)
echo ✅ Python 依赖安装完成

echo.
echo ========================================
echo   ✅ 开发环境配置完成！
echo ========================================
echo.
echo 开发命令:
echo   npm run dev          - 启动前端开发服务器
echo   npm run tauri:dev    - 启动 Tauri 开发模式
echo   npm run tauri:build  - 构建生产版本
echo.
echo 后端命令:
echo   python python-sidecar/app.py  - 启动 Python 后端
echo.
pause
