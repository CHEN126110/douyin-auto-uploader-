@echo off
chcp 65001 >nul
echo ========================================
echo 入口已收口到根目录 start_frontend.bat
echo ========================================
echo.
echo 已停用 tauri-app 下独立后端入口，避免多入口冲突。
echo 正在跳转到统一入口...
echo.
cd /d "%~dp0\.."
call "%CD%\start_frontend.bat"
