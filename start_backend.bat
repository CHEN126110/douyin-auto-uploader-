@echo off
chcp 65001 >nul
echo ========================================
echo 入口已收口到 start_frontend.bat
echo ========================================
echo.
echo 已停用独立后端入口，避免多入口冲突。
echo 正在跳转到统一入口...
echo.
cd /d "%~dp0"
call "%~dp0start_frontend.bat"
