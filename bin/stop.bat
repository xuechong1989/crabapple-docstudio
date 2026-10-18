@echo off
chcp 65001 >nul 2>&1
title 海棠文档工坊 - 停止服务

echo ============================================================
echo   海棠文档工坊 - 停止服务
echo ============================================================
echo.

set "FOUND=0"

:: ============================================================
:: 方法1: 通过端口查找并停止进程
:: ============================================================
echo [1/2] 检查端口 8000...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000" ^| findstr "LISTENING"') do (
    if not "%%a"=="0" (
        set "FOUND=1"
        echo   发现进程 PID: %%a
        taskkill /F /T /PID %%a >nul 2>&1
        echo   已停止进程 %%a
    )
)

:: ============================================================
:: 方法2: 通过进程名查找 Python 相关进程
:: ============================================================
echo.
echo [2/2] 检查 Python 服务进程...
for /f "tokens=2 delims=," %%a in ('wmic process where "commandline like '%%start_server%%'" get processid /format:csv 2^>nul ^| findstr /r "[0-9]"') do (
    if not "%%a"=="" (
        set "FOUND=1"
        echo   发现 Python 进程 PID: %%a
        taskkill /F /T /PID %%a >nul 2>&1
        echo   已停止进程 %%a
    )
)

:: ============================================================
:: 等待进程结束并验证
:: ============================================================
echo.
echo 等待进程结束...
timeout /t 2 /nobreak >nul

:: 验证端口是否释放
echo.
echo 验证端口状态...
netstat -ano 2>nul | findstr ":8000" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo.
    echo   [警告] 端口 8000 仍被占用!
    echo   请在任务管理器中手动结束相关进程
) else (
    echo   端口 8000 已释放
    echo.
    echo ============================================================
    echo   服务已停止 (浏览器窗口保持打开)
    echo ============================================================
)

echo.
echo 按任意键关闭此窗口...
pause >nul
