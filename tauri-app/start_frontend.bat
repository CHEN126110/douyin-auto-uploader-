@echo off
chcp 65001 >nul
echo 入口已收口到根目录 start_frontend.bat
echo 正在跳转到统一入口...
cd /d "%~dp0\.."
call "%CD%\start_frontend.bat"
