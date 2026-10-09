@echo off
setlocal
chcp 65001 >nul
REM Keep this entry point ASCII; PowerShell handles UTF-8 messages and exit codes.
set "START_MODE="
if /i "%~1"=="--no-pause" set "START_MODE=-NoPause"
if /i "%~1"=="--dev" set "START_MODE=-Dev"
if /i "%~2"=="--dev" set "START_MODE=%START_MODE% -Dev"
if /i "%~2"=="--no-pause" set "START_MODE=%START_MODE% -NoPause"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tauri-app\start_tauri_dev.ps1" %START_MODE%
exit /b %ERRORLEVEL%
