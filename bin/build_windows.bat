@echo off
chcp 65001 >nul 2>&1
title 海棠文档工坊 - Windows打包

echo ============================================================
echo   海棠文档工坊 - Windows打包
echo ============================================================
echo.

:: 切换到项目根目录（脚本在 bin 目录下，需要返回上层）
cd /d "%~dp0.."
call "%~dp0_paths.bat"

:: 检测 Python（避免嵌套 if/else，防止 cmd.exe 解析 bug）
echo [1/2] 检测Python环境...
set "PYTHON_CMD="
if defined DOCSTUDIO_PYTHON (
    set "PYTHON_CMD=%DOCSTUDIO_PYTHON%"
    echo   使用环境变量: %DOCSTUDIO_PYTHON%
)
if not defined PYTHON_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
    )
)
if not defined PYTHON_CMD (
    echo   [错误] 未找到Python环境!
    echo   请安装 Python 3.11+ 或设置 DOCSTUDIO_PYTHON 环境变量
    pause
    exit /b 1
)
echo   Python: %PYTHON_CMD%

echo.
echo [2/2] 开始打包 Windows 版本...
echo.

:: 运行打包脚本（仅 Windows）
"%PYTHON_CMD%" scripts/pack_release.py --platform windows

echo.
echo 按任意键关闭此窗口...
pause >nul
