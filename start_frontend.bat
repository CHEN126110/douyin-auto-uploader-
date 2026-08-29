@echo off
REM 项目根目录启动脚本 - Tauri 前端应用
REM 使用方法: 双击此文件或命令行运行 start_frontend.bat

chcp 65001 >nul
echo ========================================
echo 启动 Tauri 前端应用
echo ========================================
echo.

REM 确保在项目根目录
cd /d "%~dp0"
echo 当前目录: %CD%
echo.

REM 切换到 tauri-app 目录
cd tauri-app
echo 切换到前端目录: %CD%
echo.

REM 检查 node_modules 是否存在
if not exist "node_modules" (
    echo [提示] 检测到 node_modules 不存在，正在安装依赖...
    echo 这可能需要几分钟时间，请耐心等待...
    echo.
    call npm install
    echo.
    echo [完成] 依赖安装完成！
    echo.
)

echo [启动] 正在启动 Tauri 开发模式...
echo.
echo ========================================
echo 提示：
echo - 首次启动需要编译 Rust 代码，可能需要 2-5 分钟
echo - 编译完成后会自动打开应用窗口
echo - 开发模式下修改代码会自动热重载
echo - 按 Ctrl+C 停止开发服务器
echo ========================================
echo.

call npm run tauri:dev

pause
